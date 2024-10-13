import sqlite3

import pytest

from toolagent.tools import DatabaseTool, ToolError


@pytest.fixture
def db(shop_db):
    return DatabaseTool(shop_db, max_rows=50, timeout_ms=500)


def test_select_returns_columns_and_rows(db):
    result = db.execute("SELECT city, region FROM stores ORDER BY id")
    assert result["columns"] == ["city", "region"]
    assert result["rows"][0] == ["Seattle", "Washington"]
    assert result["row_count"] == 6
    assert "truncated" not in result


def test_joins_aggregates_and_ctes_work(db):
    result = db.execute(
        "WITH sales AS (SELECT o.store_id, SUM(oi.quantity * oi.unit_price) AS revenue FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id WHERE o.status = 'completed' GROUP BY o.store_id) "
        "SELECT s.city, ROUND(revenue, 2) FROM sales JOIN stores s ON s.id = sales.store_id ORDER BY 2 DESC"
    )
    assert result["row_count"] == 6
    assert all(row[1] > 0 for row in result["rows"])


def test_large_results_are_truncated_with_a_note(db):
    result = db.execute("SELECT * FROM order_items")
    assert result["row_count"] == 50
    assert result["truncated"] is True
    assert "Aggregate" in result["note"]


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "UPDATE products SET price = 0",
    "INSERT INTO stores VALUES (99, 'x', 'x', 'x', 'US', '2020-01-01')",
    "DROP TABLE orders",
    "CREATE TABLE evil (x)",
    "CREATE TEMP TABLE evil (x)",
    "ALTER TABLE stores ADD COLUMN x",
    "ATTACH DATABASE 'other.db' AS other",
    "PRAGMA journal_mode = DELETE",
    "PRAGMA writable_schema = ON",
    "BEGIN",
    "VACUUM",
    "VACUUM INTO 'copy.db'",
    "SELECT load_extension('evil')",
    "REPLACE INTO meta VALUES ('notes', 'x')",
])
def test_writes_and_unsafe_statements_are_refused(db, sql):
    with pytest.raises(ToolError, match="read-only"):
        db.execute(sql)


def test_database_is_unchanged_after_attempted_writes(db, shop_db):
    before = sqlite3.connect(shop_db).execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    for sql in ("DELETE FROM orders", "DROP TABLE orders"):
        with pytest.raises(ToolError):
            db.execute(sql)
    assert sqlite3.connect(shop_db).execute("SELECT COUNT(*) FROM orders").fetchone()[0] == before > 0


def test_multiple_statements_are_refused(db):
    with pytest.raises(ToolError, match="one statement"):
        db.execute("SELECT 1; DELETE FROM orders")


def test_introspection_pragmas_are_allowed(db):
    assert db.execute("SELECT name FROM pragma_table_info('orders')")["row_count"] == 6
    assert db.execute("PRAGMA table_info(stores)")["row_count"] == 6


def test_runaway_queries_are_stopped(db):
    with pytest.raises(ToolError, match="longer than 500 ms"):
        db.execute("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r")


def test_huge_values_are_refused(db):
    with pytest.raises(ToolError, match="too big"):
        db.execute("SELECT zeroblob(50000000)")


def test_unknown_table_error_points_at_the_schema(db):
    with pytest.raises(ToolError, match="no such table: sales.*schema"):
        db.execute("SELECT * FROM sales")


def test_cells_are_made_json_friendly(db):
    result = db.execute("SELECT x'00ff', printf('%.*c', 500, 'a'), 1.0 / 3")
    blob, long_text, third = result["rows"][0]
    assert blob == "<blob 2 bytes>"
    assert len(long_text) == 201 and long_text.endswith("…")
    assert third == 0.3333


def test_description_contains_schema_and_notes(db):
    description = db.description
    assert "orders(id INTEGER PK, customer_id INTEGER" in description
    assert "FK: " in description
    assert "status = 'completed'" in description


def test_missing_database_file(tmp_path):
    with pytest.raises(ToolError, match="seed-db"):
        DatabaseTool(tmp_path / "nope.db", 10, 100).execute("SELECT 1")

def dequeue_batch(data=None):
    if data is None:
        return None
    return data

def debounce_input(data=None):
    if data is None:
        return None
    return data