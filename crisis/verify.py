"""Deterministic citation/field checks; these are not semantic truth verification.

The model never grades itself. Each check is a rule over the report JSON and the exact
documents it was given:

citations   every key fact cites at least one document, and only documents that exist
numbers     every number in a fact appears in a document that fact cites
alert       alert_level equals the highest alert stated in the documents ('unknown' if none)
location    the location shares a content word with the documents
hazard      the stated hazard matches the incident's hazard
"""

from __future__ import annotations

import json
import re

from .report import max_alert
from .sources import Doc

_NUM = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")
_WORD = re.compile(r"[a-z]{3,}")
_STOP = {"the", "and", "near", "km", "of", "in", "region", "area", "areas", "coast", "off", "south", "north",
         "east", "west", "central", "southern", "northern", "eastern", "western", "county", "province", "state"}
HAZARD_WORDS = {
    "earthquake": {"earthquake", "quake", "seismic"},
    "cyclone": {"cyclone", "typhoon", "hurricane", "storm", "tropical"},
    "wildfire": {"wildfire", "fire", "forest", "bushfire"},
    "volcano": {"volcano", "volcanic", "eruption"},
    "flood": {"flood", "flooding"},
    "drought": {"drought"},
    "severe_weather": {"weather", "warning", "watch", "wind", "freeze", "fire", "storm", "flood", "heat", "snow",
                       "winter", "red", "flag", "advisory", "alert", "tornado", "thunderstorm", "hurricane", "frost"},
    "ice": {"ice", "iceberg"},
}


_CITE = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")


def numbers(text: str) -> list[float]:
    """Numbers stated in text; bracketed citation markers like [3] or [1, 2] are not claims."""
    return [float(m.replace(",", "")) for m in _NUM.findall(_CITE.sub(" ", text))]


def _haystack(d: Doc) -> str:
    return " ".join([d.title, d.text, d.time, d.updated, json.dumps(d.facts)])


def _num_supported(n: float, docs: list[Doc]) -> bool:
    for d in docs:
        for m in numbers(_haystack(d)):
            if abs(m - n) <= (0.051 if n != int(n) or m != int(m) else 0):
                return True
    return False


def verify(report: dict, docs: list[Doc], hazard: str) -> dict:
    facts_out = []
    for fact in report.get("key_facts", []):
        problems = []
        cites = fact.get("citations") or []
        valid = [c for c in cites if type(c) is int and 1 <= c <= len(docs)]
        if not cites:
            problems.append("no citation")
        if len(valid) != len(cites):
            problems.append(f"cites documents that don't exist: {[c for c in cites if c not in valid]}")
        cited = [docs[c - 1] for c in valid]
        unsupported = [n for n in numbers(fact.get("text", "")) if not _num_supported(n, cited)]
        if unsupported:
            problems.append(f"numbers not found in the cited documents: {unsupported}")
        facts_out.append({"text": fact.get("text", ""), "citations": cites, "ok": not problems, "problems": problems, "factual_status": "unverified_generated_claim"})

    expected_alert = max_alert(docs)
    alert_ok = report.get("alert_level") == expected_alert
    doc_words = {w for d in docs for w in _WORD.findall((d.title + " " + d.text + " " + (d.country or "")).lower())}
    loc_words = {w for w in _WORD.findall(report.get("location", "").lower()) if w not in _STOP}
    location_ok = bool(loc_words & doc_words)
    stated = set(_WORD.findall((report.get("hazard", "") + " " + report.get("headline", "")).lower()))
    hazard_ok = bool(stated & HAZARD_WORDS.get(hazard, {hazard}))
    n_ok = sum(f["ok"] for f in facts_out)
    return {
        "scope": "Citation, numeric-overlap and structured-field checks only; not semantic entailment or factual truth",
        "factual_verification": "not_established",
        "facts": facts_out,
        "fact_count": len(facts_out),
        "facts_grounded": n_ok,
        "alert": {"ok": alert_ok, "stated": report.get("alert_level"), "expected": expected_alert},
        "location_ok": location_ok,
        "hazard_ok": hazard_ok,
        "passed": bool(facts_out) and n_ok == len(facts_out) and alert_ok and location_ok and hazard_ok,
    }
