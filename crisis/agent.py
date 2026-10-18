"""The monitoring loop: fetch -> version -> embed -> link -> (re)write reports for changed incidents -> verify."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

import httpx

from . import link, report, retrieve, sanitize, sources, verify
from .store import Store

log = logging.getLogger("crisis")

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"},
                   "key_facts": {"type": "array", "items": {"type": "object", "properties": {
                       "text": {"type": "string"}, "citations": {"type": "array", "items": {"type": "integer"}}},
                       "required": ["text", "citations"]}}},
    "required": ["answer", "key_facts"],
}


class Agent:
    def __init__(self, state: Path, model: str = report.MODEL, use_embeddings: bool = True):
        self.state = state
        self.store = Store(state / "crisis.db")
        self.model = model
        self.use_embeddings = use_embeddings

    def ingest(self, docs: list[sources.Doc]) -> dict:
        counts = self.store.upsert(docs)
        if self.use_embeddings:
            todo = self.store.missing_embeddings()
            try:
                if todo:
                    self.store.put_embeddings(list(zip(todo, retrieve.embed([d.title + ". " + d.text for d in todo]))))
                counts["embedded"] = len(todo)
            except httpx.HTTPError as exc:
                log.warning("embeddings unavailable, keyword search only: %s", exc)
        return counts

    def relink(self) -> list[dict]:
        incidents = link.link(self.store.docs())
        self.store.save_incidents(incidents)
        return incidents

    def members(self, incident: dict) -> list[sources.Doc]:
        by_key = {d.key: d for d in self.store.docs()}
        return [by_key[k] for k in incident["members"] if k in by_key]

    def write_reports(self, limit: int = 10, kinds: tuple[str, ...] = ("llm", "baseline")) -> int:
        written = 0
        for inc in self.store.incidents()[:limit]:
            docs, quarantined = sanitize.sanitize(self.members(inc))
            for kind in kinds:
                if self.store.report(inc["incident_id"], inc["members_hash"], kind):
                    continue  # nothing changed since the last report
                rep = report.llm_report(docs, self.model) if kind == "llm" else report.baseline_report(docs)
                checked = verify.verify(rep, docs, inc["hazard"])
                checked["quarantined"] = quarantined
                self.store.save_report(inc["incident_id"], inc["members_hash"], kind, rep, checked)
                written += 1
        return written

    def cycle(self, snapshot_dir: Path | None = None, limit: int = 10) -> dict:
        if snapshot_dir is None:
            snapshot_dir = self.state / "snapshots" / dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%SZ")
            fetched = sources.snapshot(snapshot_dir)
        else:
            fetched = "replay"
        counts = self.ingest(sources.load_snapshot(snapshot_dir))
        incidents = self.relink()
        written = self.write_reports(limit)
        summary = {"snapshot": str(snapshot_dir), "fetched": fetched, "docs": counts,
                   "incidents": len(incidents), "reports_written": written}
        log.info(json.dumps(summary))
        return summary

    def ask(self, question: str, k: int = 6) -> dict:
        docs = self.store.docs()
        hits = retrieve.search(question, docs, self.store.embeddings() if self.use_embeddings else None, k=k)
        context, _ = sanitize.sanitize([d for d, _ in hits])
        if not context:
            return {"answer": "No matching documents.", "documents": [], "verification": None}
        body = {"model": self.model, "stream": False, "format": ANSWER_SCHEMA,
                "options": {"temperature": 0, "seed": 7, "num_predict": 500, "num_ctx": 8192},
                "messages": [{"role": "system", "content": report.SYSTEM.replace("situation reports", "answers")},
                             {"role": "user", "content": f"Source documents:\n\n{report.render_docs(context)}\n\n"
                                                         f"Question: {question}\n\nAnswer in two or three plain "
                                                         "sentences in the answer field. Then list key facts as short "
                                                         "sentences in your own words, each with the numbers of the documents "
                                                         "it comes from in citations. Do not copy the facts JSON or write "
                                                         "document numbers in the text. If the documents do not answer the "
                                                         "question, say so."}]}
        r = httpx.post(f"{os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')}/api/chat", json=body, timeout=300)
        r.raise_for_status()
        ans = json.loads(r.json()["message"]["content"])
        checked = verify.verify({**ans, "alert_level": "unknown", "location": "", "hazard": ""}, context, "")
        return {"answer": ans["answer"], "key_facts": checked["facts"],
                "documents": [{"n": i, "key": d.key, "title": d.title, "url": d.url} for i, d in enumerate(context, 1)]}
