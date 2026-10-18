"""crisis: snapshot feeds, run the monitoring loop, ask questions, evaluate, serve the dashboard."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from . import sources
from .agent import Agent
from .evaluate import evaluate


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="crisis")
    p.add_argument("--state", default="state")
    p.add_argument("--model", default="qwen2.5:3b")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="fetch every feed once into a folder")
    s.add_argument("--out", required=True)
    s = sub.add_parser("cycle", help="one monitoring cycle (live fetch, or --replay a snapshot)")
    s.add_argument("--replay")
    s.add_argument("--limit", type=int, default=10)
    s = sub.add_parser("watch", help="run cycles forever")
    s.add_argument("--interval", type=int, default=600)
    s.add_argument("--limit", type=int, default=10)
    s = sub.add_parser("ask", help="retrieval-grounded question answering")
    s.add_argument("question")
    s = sub.add_parser("eval", help="evaluate on a frozen snapshot")
    s.add_argument("snapshot")
    s.add_argument("--top", type=int, default=20)
    s.add_argument("--injection-cases", type=int, default=10)
    s.add_argument("--report")
    s = sub.add_parser("serve", help="dashboard at http://127.0.0.1:8790")
    s.add_argument("--port", type=int, default=8790)
    args = p.parse_args(argv)
    state = Path(args.state)

    if args.cmd == "snapshot":
        print(json.dumps(sources.snapshot(Path(args.out)), indent=2))
    elif args.cmd == "cycle":
        Agent(state, args.model).cycle(Path(args.replay) if args.replay else None, args.limit)
    elif args.cmd == "watch":
        agent = Agent(state, args.model)
        while True:
            try:
                agent.cycle(None, args.limit)
            except Exception as exc:  # a feed outage must not stop the monitor
                logging.exception("cycle failed: %s", exc)
            time.sleep(args.interval)
    elif args.cmd == "ask":
        print(json.dumps(Agent(state, args.model).ask(args.question), indent=2))
    elif args.cmd == "eval":
        result = evaluate(Path(args.snapshot), args.top, args.model, args.injection_cases)
        out = Path(args.report or f"docs/eval-{Path(args.snapshot).name}.json")
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "reports"}, indent=2))
    elif args.cmd == "serve":
        import os

        import uvicorn

        os.environ["CRISIS_STATE"] = str(state)
        uvicorn.run("crisis.api:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
