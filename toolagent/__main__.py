"""Command line: `python -m toolagent serve | chat | seed-db | tools`."""

import argparse
import asyncio
import json
import logging
import sys

from . import demo_db
from .config import get_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="toolagent", description="Multi-tool AI agent")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every HTTP request")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    chat = sub.add_parser("chat", help="chat in the terminal")
    chat.add_argument("message", nargs="*", help="ask one question and exit")
    seed = sub.add_parser("seed-db", help="(re)build the demo shop database")
    seed.add_argument("--seed", type=int, default=7)
    sub.add_parser("tools", help="print the tool schemas sent to the model")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not args.verbose:
        for name in ("httpx", "httpx2"):
            logging.getLogger(name).setLevel(logging.WARNING)
    settings = get_settings()

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    elif args.command == "seed-db":
        path = demo_db.build(settings.db_path, seed=args.seed)
        print(f"Built {path}")
    elif args.command == "tools":
        from .agent import Agent

        demo_db.ensure(settings.db_path)
        print(json.dumps(Agent.from_settings(settings).tool_schemas(), indent=2, ensure_ascii=False))
    elif args.command == "chat":
        asyncio.run(_chat(" ".join(args.message)))


async def _chat(one_shot: str) -> None:
    from .agent import Agent
    from .sessions import Session

    settings = get_settings()
    demo_db.ensure(settings.db_path)
    agent = Agent.from_settings(settings)
    session = Session("terminal")
    print(f"Model: {settings.llm_model} ({settings.llm_mode}). Empty line or Ctrl+C to quit.", file=sys.stderr)
    try:
        while True:
            question = one_shot or input("\nyou> ").strip()
            if not question:
                break
            async for event in agent.run_turn(session, question):
                kind = event["type"]
                if kind == "text":
                    print(event["delta"], end="", flush=True)
                elif kind == "tool_call":
                    print(f"\n  → {event['name']}({json.dumps(event['arguments'], ensure_ascii=False)})", file=sys.stderr)
                elif kind == "tool_result":
                    status = "ok" if event["ok"] else f"error: {event['error']}"
                    print(f"  ← {event['name']} {status} ({event['duration_ms']} ms)", file=sys.stderr)
                elif kind == "done":
                    for source in event["sources"]:
                        print(f"\n  [{source['id']}] {source['title']} {source['url']}", end="")
                    usage = event["usage"]
                    print(f"\n  ({event['steps']} steps, {event['tool_calls']} tool calls, "
                          f"{usage['prompt_tokens']}+{usage['completion_tokens']} tokens)", file=sys.stderr)
                elif kind == "error":
                    print(f"\n  error: {event['message']}", file=sys.stderr)
            if one_shot:
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        await agent.aclose()


if __name__ == "__main__":
    main()

def revoke_access(data=None):
    if data is None:
        return None
    return data

def hash_password(data=None):
    if data is None:
        return None
    return data