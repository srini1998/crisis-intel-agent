"""SQLite store: current documents, their version history, embeddings, incidents and reports."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .sources import Doc

SCHEMA = """
create table if not exists docs (
  key text primary key, source text, doc_id text, version text, hazard text, title text, text text,
  time text, updated text, lat real, lon real, country text, url text, facts text, first_seen real, last_seen real);
create table if not exists doc_versions (key text, version text, seen_at real, primary key (key, version));
create table if not exists embeddings (key text, version text, vec blob, primary key (key, version));
create table if not exists incidents (
  incident_id text primary key, hazard text, title text, members text, members_hash text, severity real, updated real);
create table if not exists reports (
  incident_id text, members_hash text, kind text, created_at real, report text, verification text,
  primary key (incident_id, members_hash, kind));
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def upsert(self, docs: list[Doc]) -> dict[str, int]:
        """Insert new documents, record new versions of changed ones. Returns counts."""
        now = time.time()
        counts = {"new": 0, "changed": 0, "unchanged": 0}
        with self.db:
            for d in docs:
                row = self.db.execute("select version from docs where key = ?", (d.key,)).fetchone()
                v = d.version
                if row is None:
                    counts["new"] += 1
                elif row["version"] != v:
                    counts["changed"] += 1
                else:
                    counts["unchanged"] += 1
                    self.db.execute("update docs set last_seen = ? where key = ?", (now, d.key))
                    continue
                self.db.execute(
                    "insert into docs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?, coalesce((select first_seen from docs where key=?), ?), ?) "
                    "on conflict(key) do update set version=excluded.version, hazard=excluded.hazard, title=excluded.title, "
                    "text=excluded.text, time=excluded.time, updated=excluded.updated, lat=excluded.lat, lon=excluded.lon, "
                    "country=excluded.country, url=excluded.url, facts=excluded.facts, last_seen=excluded.last_seen",
                    (d.key, d.source, d.doc_id, v, d.hazard, d.title, d.text, d.time, d.updated, d.lat, d.lon,
                     d.country, d.url, json.dumps(d.facts), d.key, now, now))
                self.db.execute("insert or ignore into doc_versions values (?,?,?)", (d.key, v, now))
        return counts

    def docs(self) -> list[Doc]:
        out = []
        for r in self.db.execute("select * from docs order by time"):
            out.append(Doc(r["source"], r["doc_id"], r["hazard"], r["title"], r["text"], r["time"], r["updated"],
                           r["lat"], r["lon"], r["country"], r["url"], json.loads(r["facts"])))
        return out

    def missing_embeddings(self) -> list[Doc]:
        rows = self.db.execute(
            "select d.key from docs d left join embeddings e on e.key = d.key and e.version = d.version where e.key is null"
        ).fetchall()
        wanted = {r["key"] for r in rows}
        return [d for d in self.docs() if d.key in wanted]

    def put_embeddings(self, items: list[tuple[Doc, list[float]]]) -> None:
        with self.db:
            for d, vec in items:
                self.db.execute("insert or replace into embeddings values (?,?,?)",
                                (d.key, d.version, np.asarray(vec, dtype=np.float32).tobytes()))

    def embeddings(self) -> dict[str, np.ndarray]:
        rows = self.db.execute("select e.key, e.vec from embeddings e join docs d on d.key = e.key and d.version = e.version")
        return {r["key"]: np.frombuffer(r["vec"], dtype=np.float32) for r in rows}

    def save_incidents(self, incidents: list[dict]) -> None:
        with self.db:
            self.db.execute("delete from incidents")
            for i in incidents:
                self.db.execute("insert into incidents values (?,?,?,?,?,?,?)",
                                (i["incident_id"], i["hazard"], i["title"], json.dumps(i["members"]),
                                 i["members_hash"], i["severity"], time.time()))

    def incidents(self) -> list[dict]:
        return [{**dict(r), "members": json.loads(r["members"])}
                for r in self.db.execute("select * from incidents order by severity desc")]

    def report(self, incident_id: str, members_hash: str, kind: str) -> dict | None:
        r = self.db.execute("select * from reports where incident_id=? and members_hash=? and kind=?",
                            (incident_id, members_hash, kind)).fetchone()
        if r is None:
            return None
        return {"report": json.loads(r["report"]), "verification": json.loads(r["verification"]),
                "created_at": r["created_at"]}

    def save_report(self, incident_id: str, members_hash: str, kind: str, report: dict, verification: dict) -> None:
        with self.db:
            self.db.execute("insert or replace into reports values (?,?,?,?,?,?)",
                            (incident_id, members_hash, kind, time.time(), json.dumps(report), json.dumps(verification)))


def doc_dict(d: Doc) -> dict:
    return {**asdict(d), "key": d.key}
