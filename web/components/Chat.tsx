"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { applyEvent, linkCitations, newAssistantMessage, settleTools } from "@/lib/chat";
import { readAgentEvents } from "@/lib/sse";
import type { AgentInfo, AssistantMessage, Message, Part, ToolPart } from "@/lib/types";
import { Markdown } from "./Markdown";
import { ToolCard } from "./ToolCard";
import { PlusIcon, SendIcon, StopIcon, toolIcon } from "./icons";

const EXAMPLES = [
  "Will it rain in Seattle this weekend, and do we have enough rain jackets in stock there?",
  "Which store had the most sales last month, and what's the weather there tomorrow?",
  "What are the best-selling products in Denver over the last 30 days?",
  "What's the latest on PFAS-free rain jackets?",
];

let counter = 0;
const nextId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [info, setInfo] = useState<AgentInfo | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    fetch("/api/tools")
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`);
        setInfo(body as AgentInfo);
      })
      .catch((e: Error) => setInfoError(e.message));
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const update = useCallback((id: string, fn: (m: AssistantMessage) => AssistantMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id && m.role === "assistant" ? fn(m) : m)));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      const assistantId = nextId();
      setMessages((prev) => [...prev, { role: "user", id: nextId(), text: message }, newAssistantMessage(assistantId)]);
      setInput("");
      setBusy(true);
      stickToBottom.current = true;
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ message, session_id: sessionId }),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          const body = await response.json().catch(() => ({}));
          const detail = typeof body.detail === "string" ? body.detail : `The agent API returned HTTP ${response.status}.`;
          update(assistantId, (m) => ({ ...m, status: "error", error: detail }));
          return;
        }
        for await (const event of readAgentEvents(response.body)) {
          if (event.type === "turn_start") setSessionId(event.session_id);
          update(assistantId, (m) => applyEvent(m, event));
        }
        update(assistantId, (m) =>
          m.status === "streaming" ? { ...m, status: "error", error: "The connection closed before the answer finished." } : m,
        );
      } catch (error) {
        const aborted = (error as Error).name === "AbortError";
        update(assistantId, (m) => ({
          ...m,
          status: aborted ? "stopped" : "error",
          error: aborted ? undefined : "Lost the connection to the agent.",
          parts: settleTools(m.parts, "error"),
        }));
      } finally {
        abortRef.current = null;
        setBusy(false);
        inputRef.current?.focus();
      }
    },
    [busy, sessionId, update],
  );

  const newChat = () => {
    abortRef.current?.abort();
    if (sessionId) fetch(`/api/sessions/${sessionId}`, { method: "DELETE" }).catch(() => {});
    setSessionId(null);
    setMessages([]);
    inputRef.current?.focus();
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            ◆
          </span>
          <div>
            <h1>Trailhead Ops Agent</h1>
            <p>Multi-tool AI agent demo</p>
          </div>
        </div>
        <button className="new-chat" onClick={newChat} type="button">
          <PlusIcon /> New chat
        </button>

        <section>
          <h2>Model</h2>
          {info ? (
            <p className="model">
              <span className={`dot dot-${info.llm.mode}`} aria-hidden />
              {info.llm.model}
              <span className="muted"> · {info.llm.mode === "demo" ? "scripted" : info.llm.mode}</span>
            </p>
          ) : (
            <p className="muted">{infoError ?? "Connecting…"}</p>
          )}
        </section>

        <section>
          <h2>Tools</h2>
          <ul className="tool-list">
            {(info?.tools ?? []).map((t) => (
              <li key={t.name}>
                <span className="tool-icon">{toolIcon(t.name)}</span>
                <div>
                  <code>{t.name}</code>
                  <p>{t.description.split(/(?<=\.)\s/)[0]}</p>
                  {t.name === "web_search" && <p className="muted">provider: {info?.search_provider}</p>}
                  {t.name === "get_weather" && <p className="muted">provider: {info?.weather_provider}</p>}
                </div>
              </li>
            ))}
          </ul>
          {info && (
            <p className="muted small">
              Up to {info.limits.max_steps} model calls and {info.limits.max_tool_calls} tool calls per question.
            </p>
          )}
        </section>
      </aside>

      <main className="main">
        {info?.llm.mode === "demo" && (
          <div className="banner" role="note">
            <strong>Demo mode.</strong> Replies come from a scripted stand-in model (keyword rules and templates), not an
            LLM. The tools, streaming and agent loop are real. Set <code>OPENAI_API_KEY</code> to use a real model.
          </div>
        )}
        <div
          className="messages"
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
        >
          {messages.length === 0 ? (
            <div className="empty">
              <h2>Ask something that needs live data</h2>
              <p>
                The agent decides which tools to call, runs independent calls in parallel, and chains them when one
                answer depends on another.
              </p>
              <div className="examples">
                {EXAMPLES.map((q) => (
                  <button key={q} type="button" onClick={() => send(q)} disabled={busy || !!infoError}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="msg msg-user">
                  <p>{m.text}</p>
                </div>
              ) : (
                <AssistantBubble key={m.id} message={m} />
              ),
            )
          )}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder="Ask about the weather, stock and sales, or anything on the web…"
            rows={1}
            maxLength={4000}
            aria-label="Message"
          />
          {busy ? (
            <button type="button" className="icon-button stop" onClick={() => abortRef.current?.abort()} aria-label="Stop">
              <StopIcon />
            </button>
          ) : (
            <button type="submit" className="icon-button" disabled={!input.trim()} aria-label="Send">
              <SendIcon />
            </button>
          )}
        </form>
      </main>
    </div>
  );
}

type Group = { kind: "text"; part: Part; key: string } | { kind: "tools"; step: number; parts: ToolPart[]; key: string };

/** Consecutive tool calls from the same model step are shown together: they ran in parallel. */
function group(parts: Part[]): Group[] {
  const groups: Group[] = [];
  parts.forEach((part, i) => {
    const last = groups[groups.length - 1];
    if (part.kind === "tool") {
      if (last?.kind === "tools" && last.step === part.step) last.parts.push(part);
      else groups.push({ kind: "tools", step: part.step, parts: [part], key: `t${i}` });
    } else if (part.text.trim()) {
      groups.push({ kind: "text", part, key: `x${i}` });
    }
  });
  return groups;
}

function AssistantBubble({ message }: { message: AssistantMessage }) {
  const groups = group(message.parts);
  const last = message.parts[message.parts.length - 1];
  const thinking = message.status === "streaming" && (!last || last.kind === "tool" ? true : !last.text);
  const running = message.parts.some((p) => p.kind === "tool" && p.status === "running");
  return (
    <div className="msg msg-assistant">
      {groups.map((g) =>
        g.kind === "text" ? (
          <Markdown key={g.key} text={linkCitations((g.part as { text: string }).text, message.sources)} />
        ) : (
          <div key={g.key} className="tool-group">
            <div className="tool-group-label">
              Step {g.step}
              {g.parts.length > 1 ? ` · ${g.parts.length} tools in parallel` : ""}
            </div>
            {g.parts.map((p) => (
              <ToolCard key={p.id} part={p} />
            ))}
          </div>
        ),
      )}
      {thinking && (
        <p className="thinking">
          <span className="spinner" aria-hidden /> {running ? "Running tools…" : `Thinking (step ${message.step || 1})…`}
        </p>
      )}
      {message.status === "error" && <p className="msg-error">{message.error}</p>}
      {message.status === "stopped" && <p className="muted small">Stopped.</p>}
      {message.sources.length > 0 && message.status === "done" && (
        <ol className="sources">
          {message.sources.map((s) => (
            <li key={s.id}>
              <span className="cite-id">[{s.id}]</span>
              <a href={s.url} target="_blank" rel="noreferrer noopener">
                {s.title}
              </a>
            </li>
          ))}
        </ol>
      )}
      {message.meta && (
        <p className="meta">
          {message.meta.steps} step{message.meta.steps === 1 ? "" : "s"} · {message.meta.toolCalls} tool call
          {message.meta.toolCalls === 1 ? "" : "s"} · {(message.meta.elapsedMs / 1000).toFixed(1)} s ·{" "}
          {message.meta.usage.prompt_tokens.toLocaleString("en-US")} in /{" "}
          {message.meta.usage.completion_tokens.toLocaleString("en-US")} out tokens
          {message.meta.stopped === "budget" && " · hit the tool budget"}
          {message.meta.stopped === "length" && " · cut off at the token limit"}
        </p>
      )}
    </div>
  );
}

export function warmCache(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function rotateSecret(data: unknown): unknown {
  if (!data) return null;
  return data;
}