"""Entry dispatcher: `python -m src.main serve|chat|extract`."""

from __future__ import annotations

import argparse
import json
import sys


def cli_entry() -> None:
    parser = argparse.ArgumentParser(prog="daily-news")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run FastAPI server")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8765)

    sub.add_parser("chat", help="interactive REPL")

    p_extract = sub.add_parser("extract", help="one-shot extraction")
    p_extract.add_argument("--url", required=True)
    p_extract.add_argument("--section", required=True)
    p_extract.add_argument("--no-detail", action="store_true")
    p_extract.add_argument("--max", type=int, default=20)

    args = parser.parse_args()

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("src.api:app", host=args.host, port=args.port, reload=False)
    elif args.cmd == "chat":
        from .cli import run_repl

        run_repl()
    elif args.cmd == "extract":
        from .extractor import extract_list_only, extract_news

        if args.no_detail:
            data = [
                i.model_dump()
                for i in extract_list_only(args.url, args.section, max_items=args.max)
            ]
        else:
            data = [
                r.model_dump()
                for r in extract_news(
                    args.url, args.section, with_detail=True, max_items=args.max
                )
            ]
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        print()


if __name__ == "__main__":
    cli_entry()
