import argparse

import uvicorn

from . import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="mock_services", description="Fake Tavily, Open-Meteo and LLM for offline demos")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--token-delay", type=float, default=0.02, help="seconds between streamed chunks (about three words each) from the scripted model")
    args = parser.parse_args()
    uvicorn.run(create_app(args.token_delay), host=args.host, port=args.port)


if __name__ == "__main__":
    main()

def render_template(data=None):
    if data is None:
        return None
    return data

def init_service(data=None):
    if data is None:
        return None
    return data