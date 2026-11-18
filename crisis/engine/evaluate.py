"""Score a served checkpoint on held-out incidents, through the agent's own unchanged HTTP client.

The engine is started on a local port and `crisis.report.OLLAMA_URL` points at it, so every report
goes through `report.llm_report` exactly as it would against Ollama. Each report is checked by
`crisis.verify` (citations, numbers, alert level, location, hazard) and compared field by field with
the deterministic baseline the model was trained to imitate. The same prompts are also decoded
without the JSON-schema constraint, to measure what constrained decoding buys.
"""

from __future__ import annotations

import argparse
import json
import socket
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import uvicorn

from .. import report, sources, verify
from ..agent import Agent
from .engine import Engine, SamplingParams
from .model import GPT
from .server import create_app
from .tokenizer import chat_prompt, decode, encode
from .train import report_messages

FIELDS = ("hazard", "alert_level", "location", "headline")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rate(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def _parse(text: str):
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def main(argv=None) -> dict:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="models/crisis-tiny.pt")
    p.add_argument("--snapshot", default="snapshots/2026-10-18T0217Z")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--out", default="docs/results/engine_eval.json")
    a = p.parse_args(argv)

    meta = json.loads(Path(a.model).with_suffix(".json").read_text())
    heldout = set(meta["heldout_incidents"])
    if not heldout or len(heldout) != len(meta["heldout_incidents"]):
        raise SystemExit("checkpoint metadata has no unique held-out incident keys; retrain")
    model = GPT.load(a.model).eval()
    engine = Engine(model, num_blocks=2048, block_size=16, max_batch_tokens=2048, max_seqs=16)

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(create_app(engine), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    report.OLLAMA_URL = f"http://127.0.0.1:{port}"

    agent = Agent(Path(tempfile.mkdtemp(prefix="engine-eval-")), use_embeddings=False)
    agent.ingest(sources.load_snapshot(Path(a.snapshot)))
    cases = [(inc, agent.members(inc)) for inc in agent.relink() if inc["members_hash"] in heldout]

    def run(case):
        inc, docs = case
        t = time.perf_counter()
        rep = report.llm_report(docs, model="crisis-tiny")  # the agent's own client, unchanged
        return inc, docs, rep, time.perf_counter() - t

    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.concurrency) as pool:
        results = list(pool.map(run, cases))
    wall = time.perf_counter() - t0

    # Ablation: identical prompts and budget, no schema constraint.
    free = []
    for _inc, docs in cases:
        seq = engine.submit(encode(chat_prompt(report_messages(docs))), SamplingParams(max_tokens=700, temperature=0))
        free.append(seq)
    while any(s.finish_reason is None for s in free):
        time.sleep(0.05)
    srv.should_exit = True

    rows, ver = [], {"model": [], "baseline": []}
    for inc, docs, rep, secs in results:
        base = report.baseline_report(docs)
        vm, vb = verify.verify(rep, docs, inc["hazard"]), verify.verify(base, docs, inc["hazard"])
        ver["model"].append(vm)
        ver["baseline"].append(vb)
        rows.append({"incident": inc["title"], "hazard": inc["hazard"], "seconds": round(secs, 2), "report": rep,
                     "passed": vm["passed"], "matches_baseline": {f: rep.get(f) == base.get(f) for f in FIELDS},
                     "exact_match": rep == base})

    def agg(vs):
        facts = [f for v in vs for f in v["facts"]]
        return {"reports_fully_verified": _rate([v["passed"] for v in vs]), "facts": len(facts),
                "facts_grounded": _rate([f["ok"] for f in facts]), "alert_level_correct": _rate([v["alert"]["ok"] for v in vs]),
                "location_ok": _rate([v["location_ok"] for v in vs]), "hazard_ok": _rate([v["hazard_ok"] for v in vs])}

    free_parsed = [_parse(decode(s.out)) for s in free]
    keys = set(report.SCHEMA["properties"])
    out = {
        "checkpoint": Path(a.model).name, "params": meta["params"], "snapshot": meta["snapshot"],
        "heldout_incidents": len(rows),
        "constrained": {"valid_json": _rate([isinstance(r["report"], dict) and keys <= set(r["report"]) for r in rows]),
                        **agg(ver["model"]),
                        "field_match_vs_baseline": {f: _rate([r["matches_baseline"][f] for r in rows]) for f in FIELDS},
                        "exact_match_vs_baseline": _rate([r["exact_match"] for r in rows])},
        "unconstrained": {"valid_json": _rate([p is not None for p in free_parsed]),
                          "has_all_schema_keys": _rate([p is not None and keys <= set(p) for p in free_parsed])},
        "baseline_template": agg(ver["baseline"]),
        "serving": {"concurrency": a.concurrency, "wall_seconds": round(wall, 1),
                    "reports_per_second": round(len(rows) / wall, 2),
                    "forced_token_share": round(engine.stats.forced_tokens / max(engine.stats.decode_tokens, 1), 3)},
        "rows": rows,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=2))
    return out


if __name__ == "__main__":
    main()
