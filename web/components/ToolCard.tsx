import { describeArgs, formatSql } from "@/lib/chat";
import type { ToolPart } from "@/lib/types";
import { toolIcon } from "./icons";

type Row = (string | number | null)[];
type QueryResult = { columns: string[]; rows: Row[]; row_count: number; truncated?: boolean; note?: string };
type WeatherDay = {
  date: string;
  weekday: string;
  conditions: string;
  high: number;
  low: number;
  precipitation: number;
  precipitation_chance_pct: number | null;
};
type WeatherResult = {
  location: { name: string; region?: string; country?: string; timezone?: string };
  units: { temperature: string; precipitation: string; wind: string };
  current: { temperature: number; conditions: string; feels_like: number; wind: number; local_time: string };
  daily: WeatherDay[];
  source: string;
};
type SearchResult = { provider: string; results: { id: number; title: string; url: string; snippet: string; published?: string }[] };

const LABELS: Record<string, string> = {
  web_search: "Web search",
  get_weather: "Weather",
  query_database: "Database",
};

export function ToolCard({ part }: { part: ToolPart }) {
  const summary = describeArgs(part.name, part.args);
  return (
    <details className={`tool tool-${part.status}`}>
      <summary>
        <span className="tool-icon">{toolIcon(part.name)}</span>
        <span className="tool-name">{LABELS[part.name] ?? part.name}</span>
        <span className="tool-args" title={summary}>
          {summary}
        </span>
        <span className="tool-status">
          {part.status === "running" && <span className="spinner" aria-label="running" />}
          {part.status === "ok" && `${part.cached ? "cached · " : ""}${part.durationMs} ms`}
          {part.status === "error" && "failed"}
        </span>
      </summary>
      <div className="tool-body">
        {part.status === "error" && <p className="tool-error-msg">{part.error}</p>}
        {part.name === "query_database" && <SqlBlock args={part.args} />}
        {part.status === "ok" && <ToolResult part={part} />}
        <details className="raw">
          <summary>Raw call and result</summary>
          <pre>{JSON.stringify({ arguments: part.args, result: part.data ?? part.error }, null, 2)}</pre>
        </details>
      </div>
    </details>
  );
}

function SqlBlock({ args }: { args: unknown }) {
  const sql = (args as { sql?: string } | null)?.sql;
  return sql ? <pre className="sql">{formatSql(sql)}</pre> : null;
}

function ToolResult({ part }: { part: ToolPart }) {
  if (part.name === "query_database") return <QueryTable result={part.data as QueryResult} />;
  if (part.name === "get_weather") return <Weather result={part.data as WeatherResult} />;
  if (part.name === "web_search") return <SearchResults result={part.data as SearchResult} />;
  return null;
}

function QueryTable({ result }: { result: QueryResult }) {
  if (!result?.columns) return null;
  return (
    <>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {result.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row, i) => (
              <tr key={i}>
                {row.map((v, j) => (
                  <td key={j} className={typeof v === "number" ? "num" : undefined}>
                    {v === null ? "NULL" : String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tool-note">
        {result.row_count} row{result.row_count === 1 ? "" : "s"}
        {result.truncated ? ` · ${result.note}` : ""}
      </p>
    </>
  );
}

function Weather({ result }: { result: WeatherResult }) {
  if (!result?.location) return null;
  const { location, units, current } = result;
  return (
    <>
      <p className="tool-note">
        {[location.name, location.region, location.country].filter(Boolean).join(", ")} · now {current.temperature}
        {units.temperature}, {current.conditions} · {result.source}
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Day</th>
              <th>Conditions</th>
              <th>High</th>
              <th>Low</th>
              <th>Rain</th>
            </tr>
          </thead>
          <tbody>
            {result.daily.map((d) => (
              <tr key={d.date}>
                <td>
                  {d.weekday.slice(0, 3)} {d.date.slice(5)}
                </td>
                <td>{d.conditions}</td>
                <td className="num">
                  {d.high}
                  {units.temperature}
                </td>
                <td className="num">
                  {d.low}
                  {units.temperature}
                </td>
                <td className="num">
                  {d.precipitation_chance_pct ?? "–"}% · {d.precipitation} {units.precipitation}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SearchResults({ result }: { result: SearchResult }) {
  if (!result?.results) return null;
  return (
    <ol className="search-results">
      {result.results.map((r) => (
        <li key={r.url}>
          <span className="cite-id">[{r.id}]</span>
          <div>
            <a href={r.url} target="_blank" rel="noreferrer noopener">
              {r.title}
            </a>
            <span className="url">{hostname(r.url)}</span>
            <p>{r.snippet}</p>
          </div>
        </li>
      ))}
      <li className="tool-note">via {result.provider}</li>
    </ol>
  );
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export function prefetchData(data: unknown): unknown {
  if (!data) return null;
  return data;
}