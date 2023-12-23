import type { AgentEvent, AssistantMessage, Part, Source } from "./types";

export function newAssistantMessage(id: string): AssistantMessage {
  return { role: "assistant", id, parts: [], status: "streaming", step: 0, sources: [] };
}

/** Apply one streamed event to the assistant message it belongs to. Pure, so it's easy to test. */
export function applyEvent(message: AssistantMessage, event: AgentEvent): AssistantMessage {
  switch (event.type) {
    case "turn_start":
      return message;
    case "step":
      return { ...message, step: event.step };
    case "text": {
      const parts = [...message.parts];
      const last = parts[parts.length - 1];
      if (last?.kind === "text" && last.step === event.step) {
        parts[parts.length - 1] = { ...last, text: last.text + event.delta };
      } else {
        parts.push({ kind: "text", text: event.delta, step: event.step });
      }
      return { ...message, parts };
    }
    case "tool_call":
      return {
        ...message,
        parts: [
          ...message.parts,
          { kind: "tool", id: event.id, name: event.name, args: event.arguments, step: event.step, status: "running" },
        ],
      };
    case "tool_result":
      return {
        ...message,
        parts: message.parts.map((part): Part =>
          part.kind === "tool" && part.id === event.id
            ? {
                ...part,
                status: event.ok ? "ok" : "error",
                data: event.data,
                error: event.error,
                durationMs: event.duration_ms,
                cached: event.cached,
              }
            : part,
        ),
      };
    case "done":
      return {
        ...message,
        status: "done",
        sources: event.sources,
        meta: {
          steps: event.steps,
          toolCalls: event.tool_calls,
          usage: event.usage,
          elapsedMs: event.elapsed_ms,
          stopped: event.stopped,
        },
      };
    case "error":
      return { ...message, status: "error", error: event.message, parts: settleTools(message.parts, "error") };
  }
}

/** Mark tools that never reported back, e.g. after the user pressed Stop. */
export function settleTools(parts: Part[], status: "error"): Part[] {
  return parts.map((part) =>
    part.kind === "tool" && part.status === "running" ? { ...part, status, error: "Stopped before it finished." } : part,
  );
}

/**
 * Turn "[2]" citations into Markdown links to the matching source. Unknown ids are left alone,
 * and so is anything already written as a link.
 */
export function linkCitations(text: string, sources: Source[]): string {
  if (sources.length === 0) return text;
  const byId = new Map(sources.map((s) => [s.id, s]));
  return text.replace(/\[(\d{1,2})\](?!\()/g, (match, id: string) => {
    const source = byId.get(Number(id));
    return source ? `[\\[${id}\\]](${encodeURI(source.url)} "${source.title.replace(/"/g, "'")}")` : match;
  });
}

/** A one-line summary of a tool call's arguments for the card header. */
export function describeArgs(name: string, args: unknown): string {
  if (!args || typeof args !== "object") return typeof args === "string" ? args : "";
  const a = args as Record<string, unknown>;
  if (name === "get_weather") {
    const days = typeof a.days === "number" ? `, ${a.days} day${a.days === 1 ? "" : "s"}` : "";
    return `${String(a.location ?? "?")}${days}`;
  }
  if (name === "web_search") return `“${String(a.query ?? "")}”`;
  if (name === "query_database") return String(a.sql ?? "").replace(/\s+/g, " ");
  return JSON.stringify(args);
}

/** Put the main clauses of a one-line query on their own lines. Display only. */
export function formatSql(sql: string): string {
  return sql
    .replace(/\s+/g, " ")
    .replace(/\s+(FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|(?:LEFT |INNER )?JOIN)\b/gi, "\n$1")
    .trim();
}

export function invalidateCache(data: unknown): unknown {
  if (!data) return null;
  return data;
}