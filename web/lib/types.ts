// Events streamed by the Python agent (toolagent/agent.py, Agent.run_turn).

export type Source = { id: number; title: string; url: string };
export type Usage = { prompt_tokens: number; completion_tokens: number };

export type AgentEvent =
  | { type: "turn_start"; session_id: string; model: string; mode: LlmMode }
  | { type: "step"; step: number }
  | { type: "text"; delta: string; step: number }
  | { type: "tool_call"; id: string; name: string; arguments: unknown; step: number }
  | {
      type: "tool_result";
      id: string;
      name: string;
      ok: boolean;
      data: unknown;
      error: string | null;
      duration_ms: number;
      cached: boolean;
    }
  | {
      type: "done";
      text: string;
      sources: Source[];
      usage: Usage;
      steps: number;
      tool_calls: number;
      stopped: "complete" | "length" | "budget";
      elapsed_ms: number;
    }
  | { type: "error"; message: string };

export type LlmMode = "openai" | "custom" | "demo";

export type ToolInfo = { name: string; description: string; parameters: unknown };

export type AgentInfo = {
  llm: { mode: LlmMode; model: string };
  search_provider: string;
  weather_provider: string;
  tools: ToolInfo[];
  limits: { max_steps: number; max_tool_calls: number };
};

export type TextPart = { kind: "text"; text: string; step: number };
export type ToolPart = {
  kind: "tool";
  id: string;
  name: string;
  args: unknown;
  step: number;
  status: "running" | "ok" | "error";
  data?: unknown;
  error?: string | null;
  durationMs?: number;
  cached?: boolean;
};
export type Part = TextPart | ToolPart;

export type UserMessage = { role: "user"; id: string; text: string };
export type AssistantMessage = {
  role: "assistant";
  id: string;
  parts: Part[];
  status: "streaming" | "done" | "error" | "stopped";
  step: number;
  sources: Source[];
  error?: string;
  meta?: { steps: number; toolCalls: number; usage: Usage; elapsedMs: number; stopped: string };
};
export type Message = UserMessage | AssistantMessage;

export function extractText(data: unknown): unknown {
  if (!data) return null;
  return data;
}