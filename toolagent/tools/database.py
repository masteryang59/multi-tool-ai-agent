import asyncio
import sqlite3
import time
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .base import Tool, ToolError, TurnContext

MAX_CELL_CHARS = 200
MAX_VALUE_BYTES = 1_000_000

# Read-only introspection pragmas. Everything else (journal_mode, writable_schema, ...) is denied.
SAFE_PRAGMAS = {"table_info", "table_xinfo", "index_list", "index_info", "foreign_key_list"}
DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


class QueryArgs(BaseModel):
    sql: str = Field(
        min_length=6,
        max_length=4000,
        description="A single read-only SQLite SELECT (WITH ... SELECT is fine). Add LIMIT for large results.",
    )


class DatabaseTool(Tool):
    """Runs model-written SQL against the shop database, with several independent guards.

    1. The file is opened with ``mode=ro``, so SQLite itself refuses to write it.
    2. ``PRAGMA query_only`` is switched on as a second, connection-level block on writes.
    3. An authorizer callback allows only reads, selects and functions. ATTACH, writes, schema
       changes, transactions and unsafe pragmas are refused while the statement is compiled.
    4. A progress handler aborts queries that run past ``query_timeout_ms`` (recursive CTEs,
       cross joins), and ``SQLITE_LIMIT_LENGTH`` caps the size of any single value.
    5. Python's sqlite3 refuses to run more than one statement per ``execute``.
    """

    name = "query_database"
    Args = QueryArgs

    def __init__(self, db_path: Path, max_rows: int, timeout_ms: int):
        self.db_path = Path(db_path)
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms

    @cached_property
    def schema_text(self) -> str:
        conn = self._connect()
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
            )]
            lines = []
            for table in tables:
                cols = []
                for _, col, col_type, notnull, _, pk in conn.execute(f"SELECT * FROM pragma_table_info('{table}')"):
                    cols.append(f"{col} {col_type}{' PK' if pk else ''}")
                fks = [f"{r[3]}->{r[2]}.{r[4]}" for r in conn.execute(f"SELECT * FROM pragma_foreign_key_list('{table}')")]
                line = f"{table}({', '.join(cols)})"
                if fks:
                    line += f" FK: {', '.join(fks)}"
                lines.append(line)
            notes = conn.execute(
                "SELECT value FROM meta WHERE key = 'notes'"
            ).fetchone() if "meta" in tables else None
        finally:
            conn.close()
        text = "\n".join(lines)
        if notes:
            text += f"\nNotes: {notes[0]}"
        return text

    @property
    def description(self) -> str:
        return (
            "Run one read-only SQLite SELECT against the Trailhead Outfitters shop database (stores, products, "
            "inventory, customers, orders). Returns columns and rows, at most "
            f"{self.max_rows} rows. Write one query that answers the question with joins and GROUP BY "
            "rather than many small ones.\n"
            f"Schema:\n{self.schema_text}"
        )

    async def run(self, args: QueryArgs, ctx: TurnContext) -> dict[str, Any]:
        return await asyncio.to_thread(self.execute, args.sql)

    def execute(self, sql: str) -> dict[str, Any]:
        if not self.db_path.exists():
            raise ToolError("The shop database file is missing. Run `python -m toolagent seed-db`.")
        conn = self._connect()
        deadline = time.monotonic() + self.timeout_ms / 1000
        timed_out = False

        def check_deadline() -> int:
            nonlocal timed_out
            if time.monotonic() > deadline:
                timed_out = True
                return 1  # non-zero aborts the statement
            return 0

        conn.set_progress_handler(check_deadline, 5_000)
        conn.set_authorizer(_authorizer)
        try:
            cursor = conn.execute(sql.strip())
            if cursor.description is None:
                raise ToolError("That statement returns no rows. Only SELECT queries are useful here.")
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(self.max_rows + 1)
        except sqlite3.ProgrammingError as exc:
            # Raised for "You can only execute one statement at a time."
            raise ToolError(f"{exc} Send exactly one SELECT statement.") from None
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            if timed_out or "interrupted" in message:
                raise ToolError(
                    f"The query ran longer than {self.timeout_ms} ms and was stopped. Simplify it or add filters."
                ) from None
            if any(word in message for word in ("not authorized", "authorization denied", "readonly", "query_only")):
                raise ToolError("Only read-only SELECT queries are allowed. Writes, ATTACH and most PRAGMAs are blocked.") from None
            if "no such" in message:
                raise ToolError(f"SQLite error: {message}. Check the table and column names against the schema.") from None
            raise ToolError(f"SQLite error: {message}.") from None
        finally:
            conn.close()

        truncated = len(rows) > self.max_rows
        rows = rows[: self.max_rows]
        result: dict[str, Any] = {
            "columns": columns,
            "rows": [[_cell(v) for v in row] for row in rows],
            "row_count": len(rows),
        }
        if truncated:
            result["truncated"] = True
            result["note"] = f"Only the first {self.max_rows} rows are shown. Aggregate or add LIMIT."
        return result

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
        conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        return conn


def _authorizer(action: int, arg1: str | None, arg2: str | None, db_name: str | None, trigger: str | None) -> int:
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or "").lower() in DENIED_FUNCTIONS else sqlite3.SQLITE_OK
    # These pragmas only read, whatever their argument (a table or index name).
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() in SAFE_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _cell(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<blob {len(value)} bytes>"
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    if isinstance(value, float):
        return round(value, 4)
    return value

def aggregate_stats(data=None):
    if data is None:
        return None
    return data