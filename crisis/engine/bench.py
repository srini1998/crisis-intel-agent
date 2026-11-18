"""Static vs continuous batching on the same engine, model and workload.

Requests arrive as a Poisson process. Prompts are the real report prompts from the snapshot;
output lengths are drawn from a long-tailed range and EOS is ignored, so both schedulers do exactly
the same work and differ only in when they admit requests. Static batching waits for a whole batch
to finish before admitting more (the head-of-line blocking of a naive server); continuous batching
admits at every step and mixes prefill chunks with decode rows.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

import torch

from .engine import Engine, SamplingParams
from .model import GPT, Config
from .tokenizer import chat_prompt, encode
from .train import build_examples


def _pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def workload(snapshot: Path, n: int, rate: float, seed: int, max_prompt: int):
    rows, held = build_examples(snapshot, seed)
    prompts = [p for p in (encode(chat_prompt(r["messages"])) for r in rows + held) if len(p) <= max_prompt]
    rng, t, out = random.Random(seed), 0.0, []
    for _ in range(n):
        t += rng.expovariate(rate)
        out_len = min(400, int(rng.paretovariate(1.5) * 40))  # most short, a few long
        out.append((t, rng.choice(prompts), out_len))
    return out


def run(model, reqs, mode: str, args) -> dict:
    eng = Engine(model, args.num_blocks, args.block_size, args.max_batch_tokens, args.max_seqs, mode)
    seqs, i, t0 = [], 0, time.perf_counter()
    with torch.inference_mode():
        while i < len(reqs) or eng.has_work():
            now = time.perf_counter() - t0
            while i < len(reqs) and reqs[i][0] <= now:
                at, prompt, n = reqs[i]
                s = eng.submit(prompt, SamplingParams(max_tokens=n, ignore_eos=True))
                s.arrival = t0 + at  # time waiting behind a running step counts as queueing
                seqs.append(s)
                i += 1
            if eng.has_work():
                eng.step()
            elif i < len(reqs):
                time.sleep(max(0.0, reqs[i][0] - (time.perf_counter() - t0)))
    wall = time.perf_counter() - t0
    ttft = [s.first_token_at - s.arrival for s in seqs]
    e2e = [s.finished_at - s.arrival for s in seqs]
    tpot = [(s.finished_at - s.first_token_at) / max(len(s.out) - 1, 1) for s in seqs]
    out_tokens = sum(len(s.out) for s in seqs)
    st = eng.stats
    return {"mode": mode, "requests": len(seqs), "wall_seconds": round(wall, 2),
            "output_tokens_per_second": round(out_tokens / wall, 1), "requests_per_second": round(len(seqs) / wall, 2),
            "ttft_p50": _pct(ttft, .5), "ttft_p95": _pct(ttft, .95), "e2e_p50": _pct(e2e, .5), "e2e_p95": _pct(e2e, .95),
            "tpot_ms_p50": round(1000 * statistics.median(tpot), 1), "steps": st.steps,
            "mean_rows_per_step": round(st.batch_rows / max(st.steps, 1), 2), "preemptions": st.preemptions}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="models/crisis-tiny.pt")
    p.add_argument("--snapshot", default="snapshots/2026-10-18T0217Z")
    p.add_argument("--requests", type=int, default=64)
    p.add_argument("--rates", default="2,4,8", help="comma-separated arrival rates, requests per second")
    p.add_argument("--num-blocks", type=int, default=2048)
    p.add_argument("--block-size", type=int, default=16)
    p.add_argument("--max-batch-tokens", type=int, default=1024)
    p.add_argument("--max-seqs", type=int, default=16)
    p.add_argument("--max-prompt", type=int, default=1600)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="docs/results/engine_bench.json")
    a = p.parse_args(argv)
    torch.manual_seed(a.seed)
    model = (GPT.load(a.model) if Path(a.model).exists() else GPT(Config())).eval()
    results = []
    for rate in (float(r) for r in a.rates.split(",")):
        reqs = workload(Path(a.snapshot), a.requests, rate, a.seed, a.max_prompt)
        for mode in ("static", "continuous"):
            r = {"rate": rate, **run(model, reqs, mode, a)}
            print(json.dumps(r), flush=True)
            results.append(r)
    meta = {"threads": torch.get_num_threads(), "device": "cpu", "params": model.n_params(), "args": vars(a)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"meta": meta, "results": results}, indent=2))


if __name__ == "__main__":
    main()
