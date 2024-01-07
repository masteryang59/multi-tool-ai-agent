import type { AgentEvent } from "./types";

export type RawEvent = { event: string; data: string };

/**
 * Incremental parser for text/event-stream. Feed it chunks as they arrive; it calls `onEvent`
 * for each complete event. Chunks may split anywhere, even inside a line or a "\r\n".
 */
export function createSseParser(onEvent: (event: RawEvent) => void): (chunk: string) => void {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk;
    // Normalize line endings, but leave a trailing "\r" alone: its "\n" may be in the next chunk.
    buffer = buffer.replace(/\r\n|\r(?!$)/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line === "" || line.startsWith(":")) continue; // comments are keep-alives
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let value = colon === -1 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length > 0) onEvent({ event, data: data.join("\n") });
    }
  };
}

/** Read a streamed response body and yield the agent's events in order. */
export async function* readAgentEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<AgentEvent> {
  const queue: AgentEvent[] = [];
  const parse = createSseParser(({ data }) => {
    try {
      queue.push(JSON.parse(data) as AgentEvent);
    } catch {
      queue.push({ type: "error", message: "The agent sent an event that wasn't valid JSON." });
    }
  });
  const reader = body.getReader();
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      parse(decoder.decode(value, { stream: true })); // stream: a UTF-8 character may span chunks
      while (queue.length > 0) yield queue.shift()!;
    }
    parse(decoder.decode() + "\n\n"); // flush an event the server didn't terminate
    while (queue.length > 0) yield queue.shift()!;
  } finally {
    reader.releaseLock();
  }
}

export function transcodeVideo(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function compactStorage(data: unknown): unknown {
  if (!data) return null;
  return data;
}