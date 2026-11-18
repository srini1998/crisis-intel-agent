"""Train the small byte-level model the engine serves in tests and benchmarks.

The task is distillation: given the exact prompt the agent sends for a situation report, produce
the deterministic template report as JSON. Incidents are split by a seeded shuffle; the held-out
split (identified by each incident's content hash) is never trained on and is what
`crisis-engine eval` reports on.

This model is a test fixture for the serving stack, not a useful report writer. On a machine
with real weights, point the agent at Ollama or any OpenAI-compatible server instead.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import tempfile
import time
from pathlib import Path

import torch
import torch.nn.functional as F

from .. import report, sources
from ..agent import Agent
from .model import GPT, Config
from .tokenizer import EOS, chat_prompt, encode


def report_messages(docs) -> list[dict]:
    user = (f"Source documents:\n\n{report.render_docs(docs)}\n\nWrite the situation report as JSON. "
            "Use 2 to 5 key facts and 1 to 3 things to watch.")
    return [{"role": "system", "content": report.SYSTEM}, {"role": "user", "content": user}]


def build_examples(snapshot: Path, seed: int = 0, holdout: float = 0.2):
    agent = Agent(Path(tempfile.mkdtemp(prefix="engine-train-")), use_embeddings=False)
    agent.ingest(sources.load_snapshot(snapshot))
    rows = []
    for inc in agent.relink():
        docs = agent.members(inc)
        target = json.dumps(report.baseline_report(docs), separators=(",", ":"))
        rows.append({"incident": inc["title"], "key": inc["members_hash"], "messages": report_messages(docs), "target": target})
    random.Random(seed).shuffle(rows)
    k = int(len(rows) * holdout)
    return rows[k:], rows[:k]


def tensors(rows, max_seq: int):
    out = []
    for r in rows:
        p = encode(chat_prompt(r["messages"]))
        t = encode(r["target"], bos=False) + [EOS]
        ids = (p + t)[:max_seq]
        out.append((ids, len(p)))
    return out


def batch_loss(model, items):
    T = max(len(ids) for ids, _ in items)
    x = torch.zeros(len(items), T, dtype=torch.long)
    y = torch.full((len(items), T), -100, dtype=torch.long)
    for i, (ids, plen) in enumerate(items):
        x[i, :len(ids)] = torch.tensor(ids)
        y[i, plen - 1:len(ids) - 1] = torch.tensor(ids[plen:])  # loss on the answer only
    logits = model(x)
    return F.cross_entropy(logits.reshape(-1, logits.shape[-1]), y.reshape(-1), ignore_index=-100)


def main(argv=None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", default="snapshots/2026-10-18T0217Z")
    p.add_argument("--out", default="models/crisis-tiny.pt")
    p.add_argument("--steps", type=int, default=1500)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--d-model", type=int, default=256)
    p.add_argument("--layers", type=int, default=4)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    torch.manual_seed(a.seed)
    cfg = Config(d_model=a.d_model, n_layer=a.layers, n_head=4, max_seq=2048)
    train_rows, val_rows = build_examples(Path(a.snapshot), a.seed)
    train, val = tensors(train_rows, cfg.max_seq), tensors(val_rows, cfg.max_seq)
    model = GPT(cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    print(f"params={model.n_params():,} train={len(train)} val={len(val)}", flush=True)
    log, rng, t0, best = [], random.Random(a.seed), time.time(), float("inf")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    for step in range(1, a.steps + 1):
        lr = a.lr * min(1, step / 100) * 0.5 * (1 + math.cos(math.pi * step / a.steps))
        for g in opt.param_groups:
            g["lr"] = lr
        model.train()
        loss = batch_loss(model, rng.sample(train, min(a.batch, len(train))))
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % 100 == 0 or step == a.steps:
            model.eval()
            with torch.no_grad():
                vl = sum(batch_loss(model, val[i:i + 8]).item() * len(val[i:i + 8]) for i in range(0, len(val), 8)) / len(val)
            log.append({"step": step, "train_loss": round(loss.item(), 4), "val_loss": round(vl, 4),
                        "seconds": round(time.time() - t0)})
            print(log[-1], flush=True)
            if vl < best:  # keep the checkpoint that generalizes best; 150 examples overfit quickly
                best = vl
                model.save(a.out)
    Path(a.out).with_suffix(".json").write_text(json.dumps({
        "snapshot": Path(a.snapshot).name, "seed": a.seed, "params": model.n_params(), "config": vars(a),
        "train_incidents": len(train), "best_val_loss": round(best, 4), "heldout_incidents": [r["key"] for r in val_rows], "log": log}, indent=2))


if __name__ == "__main__":
    main()
