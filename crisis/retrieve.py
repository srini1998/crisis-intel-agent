"""Hybrid retrieval: BM25 keyword ranking fused with local-embedding similarity (reciprocal rank fusion)."""

from __future__ import annotations

import math
import os
import re
from collections import Counter

import httpx
import numpy as np

from .sources import Doc

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = "nomic-embed-text"
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def embed(texts: list[str], kind: str = "document") -> list[list[float]]:
    prefix = "search_document: " if kind == "document" else "search_query: "
    out = []
    for i in range(0, len(texts), 32):
        r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": [prefix + t for t in texts[i:i + 32]]},
                       timeout=120)
        r.raise_for_status()
        out.extend(r.json()["embeddings"])
    return out


class BM25:
    def __init__(self, docs: list[Doc], k1: float = 1.4, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tf = [Counter(tokens(d.title + " " + d.text)) for d in docs]
        self.len = [sum(tf.values()) for tf in self.tf]
        self.avg = sum(self.len) / max(len(self.len), 1)
        df = Counter(t for tf in self.tf for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for tf, length in zip(self.tf, self.len):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg))
            out.append(s)
        return out


def search(query: str, docs: list[Doc], vectors: dict[str, np.ndarray] | None, k: int = 8) -> list[tuple[Doc, float]]:
    if not docs:
        return []
    bm = BM25(docs).scores(query)
    rankings = [sorted(range(len(docs)), key=lambda i: -bm[i])]
    if vectors:
        try:
            qv = np.asarray(embed([query], kind="query")[0], dtype=np.float32)
            sims = []
            for d in docs:
                v = vectors.get(d.key)
                sims.append(float(qv @ v / (np.linalg.norm(qv) * np.linalg.norm(v))) if v is not None else -1.0)
            rankings.append(sorted(range(len(docs)), key=lambda i: -sims[i]))
        except httpx.HTTPError:
            pass  # keyword ranking alone if the embedding model is unavailable
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking):
            fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank)
    best = sorted(fused, key=lambda i: -fused[i])[:k]
    return [(docs[i], round(fused[i], 5)) for i in best if bm[i] > 0 or vectors]
