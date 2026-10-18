"""Group documents from different publishers that describe the same real-world incident.

USGS and GDACS both report large earthquakes; GDACS and NASA EONET both track wildfires
and cyclones. Linking is rule-based and explainable: same hazard family, within a
hazard-specific distance and time window. Earthquake links are additionally required
to agree on magnitude, which gives an independent check on the linker (see eval).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math

from .sources import ALERT_ORDER, Doc

# hazard -> (max distance km, max time gap hours)
WINDOWS = {
    "earthquake": (100, 24),
    "cyclone": (600, 24 * 7),
    "wildfire": (40, 24 * 14),
    "volcano": (30, 24 * 30),
    "flood": (300, 24 * 14),
    "drought": (800, 24 * 60),
}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _t(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")) if iso else dt.datetime.min.replace(tzinfo=dt.UTC)


def compatible(a: Doc, b: Doc) -> bool:
    if a.source == b.source or a.hazard != b.hazard:
        return False  # one publisher never reports the same incident twice under different ids here
    if a.hazard == "severe_weather":
        return False
    window = WINDOWS.get(a.hazard)
    if window is None or None in (a.lat, a.lon, b.lat, b.lon):
        return False
    km, hours = window
    if haversine_km((a.lat, a.lon), (b.lat, b.lon)) > km:
        return False
    if abs((_t(a.time) - _t(b.time)).total_seconds()) > hours * 3600:
        return False
    if a.hazard == "earthquake":
        ma, mb = a.facts.get("magnitude"), b.facts.get("magnitude")
        if ma is None or mb is None or abs(ma - mb) > 0.5:
            return False
    return True


def severity(members: list[Doc]) -> float:
    """Ranking score for the incident list (not shown as a fact)."""
    score = 0.0
    for d in members:
        alert = ALERT_ORDER.get((d.facts.get("alert_level") or "").lower(), 0)
        score = max(score, alert * 2.0)
        if d.hazard == "earthquake" and d.facts.get("magnitude"):
            score = max(score, d.facts["magnitude"] - 4.0 + alert * 2.0)
        if d.source == "nws":
            score = max(score, 2.5 if d.facts.get("severity") == "Extreme" else 1.0)
        if d.facts.get("tsunami_flag"):
            score += 1.0
    return round(score, 2)


def link(docs: list[Doc]) -> list[dict]:
    """Single-link clustering over compatible pairs (union-find)."""
    parent = list(range(len(docs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            if compatible(docs[i], docs[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[Doc]] = {}
    for i, d in enumerate(docs):
        groups.setdefault(find(i), []).append(d)
    incidents = []
    for members in groups.values():
        members.sort(key=lambda d: (d.source, d.doc_id))
        anchor = min(members, key=lambda d: (d.time, d.key))
        keys = [m.key for m in members]
        incidents.append({
            "incident_id": hashlib.sha1(anchor.key.encode()).hexdigest()[:12],
            "hazard": anchor.hazard,
            "title": max(members, key=lambda d: len(d.title)).title,
            "members": keys,
            "members_hash": hashlib.sha1("|".join(f"{m.key}@{m.version}" for m in members).encode()).hexdigest()[:12],
            "severity": severity(members),
            "sources": sorted({m.source for m in members}),
        })
    return sorted(incidents, key=lambda i: -i["severity"])
