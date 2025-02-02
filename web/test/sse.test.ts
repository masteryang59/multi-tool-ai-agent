import { describe, expect, it } from "vitest";
import { createSseParser, readAgentEvents, type RawEvent } from "../lib/sse";

function parseAll(chunks: string[]): RawEvent[] {
  const events: RawEvent[] = [];
  const feed = createSseParser((e) => events.push(e));
  chunks.forEach(feed);
  return events;
}

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === "string" ? encoder.encode(c) : c);
      controller.close();
    },
  });
}

describe("createSseParser", () => {
  it("parses named events", () => {
    expect(parseAll(['event: text\ndata: {"a":1}\n\n'])).toEqual([{ event: "text", data: '{"a":1}' }]);
  });

  it("handles events split across chunks at any point", () => {
    const whole = 'event: step\ndata: {"step":1}\n\nevent: text\ndata: {"delta":"hi"}\n\n';
    for (let i = 1; i < whole.length; i++) {
      expect(parseAll([whole.slice(0, i), whole.slice(i)])).toEqual([
        { event: "step", data: '{"step":1}' },
        { event: "text", data: '{"delta":"hi"}' },
      ]);
    }
  });

  it("accepts CRLF line endings, even when a CRLF is split between chunks", () => {
    expect(parseAll(["event: a\r\ndata: 1\r", "\n\r\n"])).toEqual([{ event: "a", data: "1" }]);
  });

  it("joins multi-line data and skips comments", () => {
    expect(parseAll([": keep-alive\n\ndata: one\ndata: two\n\n"])).toEqual([{ event: "message", data: "one\ntwo" }]);
  });

  it("waits for the blank line before emitting", () => {
    expect(parseAll(["data: partial\n"])).toEqual([]);
  });
});

describe("readAgentEvents", () => {
  it("yields parsed agent events in order", async () => {
    const body = streamOf([
      'event: turn_start\ndata: {"type":"turn_start","session_id":"s1","model":"m","mode":"demo"}\n\n',
      'event: text\ndata: {"type":"text","delta":"Hel',
      'lo","step":1}\n\n',
    ]);
    const events = [];
    for await (const e of readAgentEvents(body)) events.push(e);
    expect(events.map((e) => e.type)).toEqual(["turn_start", "text"]);
    expect(events[1]).toMatchObject({ delta: "Hello" });
  });

  it("decodes a multi-byte character split between chunks", async () => {
    const bytes = new TextEncoder().encode('data: {"type":"text","delta":"12°C","step":1}\n\n');
    const cut = bytes.indexOf(0xb0); // second byte of "°"
    const events = [];
    for await (const e of readAgentEvents(streamOf([bytes.slice(0, cut), bytes.slice(cut)]))) events.push(e);
    expect(events[0]).toMatchObject({ delta: "12°C" });
  });

  it("turns malformed JSON into an error event instead of throwing", async () => {
    const events = [];
    for await (const e of readAgentEvents(streamOf(["data: {nope\n\n"]))) events.push(e);
    expect(events[0].type).toBe("error");
  });
});

export function reportError(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function spanContext(data: unknown): unknown {
  if (!data) return null;
  return data;
}