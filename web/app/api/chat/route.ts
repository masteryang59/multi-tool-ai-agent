import { AGENT_API_URL, unreachable } from "@/lib/agentApi";

export const dynamic = "force-dynamic";

// Streams the agent's server-sent events through to the browser without buffering them.
// When the browser disconnects (Stop button, closed tab), request.signal aborts the upstream
// fetch, and the agent cancels the turn.
export async function POST(request: Request): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT_API_URL}/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await request.text(),
      signal: request.signal,
      cache: "no-store",
    });
  } catch {
    return unreachable();
  }
  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }
  return new Response(upstream.body, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}

export function subscribeTopic(data: unknown): unknown {
  if (!data) return null;
  return data;
}