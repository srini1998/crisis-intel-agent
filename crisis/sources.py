"""Live, free, keyless disaster feeds and their normalization into one document shape.

| source | publisher | licence / terms |
|---|---|---|
| usgs  | USGS Earthquake Hazards Program, M4.5+ past week | US Government work, public domain |
| gdacs | Global Disaster Alert and Coordination System (UN/EC JRC) | free public service; not redistributed in this repo |
| eonet | NASA Earth Observatory Natural Event Tracker | NASA open data |
| nws   | US National Weather Service active Severe/Extreme alerts | US Government work, public domain |

Everything a feed says is treated as untrusted data. Free text (notably NWS descriptions)
is passed to the model as quoted material, never as instructions.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

USER_AGENT = "crisis-intel-agent/0.1 (portfolio research; github.com/srini1998)"
FEEDS = {
    "usgs": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
    "gdacs": "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP",
    "eonet": "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=14",
    "nws": "https://api.weather.gov/alerts/active?severity=Extreme,Severe",
}
ALERT_ORDER = {"green": 1, "yellow": 2, "orange": 3, "red": 4}
GDACS_HAZARD = {"EQ": "earthquake", "TC": "cyclone", "FL": "flood", "VO": "volcano", "WF": "wildfire", "DR": "drought"}
EONET_HAZARD = {"wildfires": "wildfire", "volcanoes": "volcano", "severeStorms": "cyclone", "floods": "flood",
                "earthquakes": "earthquake", "drought": "drought", "seaLakeIce": "ice", "landslides": "landslide",
                "dustHaze": "dust", "tempExtremes": "temperature", "snow": "snow", "manmade": "manmade"}


@dataclass
class Doc:
    source: str
    doc_id: str
    hazard: str
    title: str
    text: str
    time: str                      # ISO 8601 UTC, when the event happened / alert became effective
    updated: str                   # ISO 8601 UTC, last modification by the publisher
    lat: float | None
    lon: float | None
    country: str | None
    url: str
    facts: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.doc_id}"

    @property
    def version(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:16]


def _iso_ms(ms: int | None) -> str:
    return dt.datetime.fromtimestamp((ms or 0) / 1000, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(text: str | None) -> str:
    if not text:
        return ""
    t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(source: str, timeout: float = 30) -> dict:
    r = httpx.get(FEEDS[source], headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json"},
                  timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def snapshot(out_dir: Path) -> dict[str, int]:
    """Fetch every feed once and store the raw responses, so a run can be replayed exactly."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for source in FEEDS:
        try:
            raw = fetch(source)
        except httpx.HTTPError as exc:
            counts[source] = f"error: {exc}"
            continue
        (out_dir / f"{source}.json").write_text(json.dumps(raw))
        counts[source] = len(raw.get("features") or raw.get("events") or [])
    (out_dir / "manifest.json").write_text(json.dumps(
        {"fetched_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "feeds": FEEDS, "counts": counts}, indent=2))
    return counts


def normalize_usgs(raw: dict) -> list[Doc]:
    docs = []
    for f in raw.get("features", []):
        p, (lon, lat, depth) = f["properties"], f["geometry"]["coordinates"]
        if p.get("type") != "earthquake" or p.get("mag") is None:
            continue
        facts = {"magnitude": round(float(p["mag"]), 1), "depth_km": round(float(depth), 1),
                 "tsunami_flag": bool(p.get("tsunami")), "felt_reports": p.get("felt"),
                 "alert_level": (p.get("alert") or None), "status": p.get("status")}
        text = (f"Magnitude {facts['magnitude']} earthquake, {p.get('place') or 'location not named'}, "
                f"depth {facts['depth_km']} km, at {_iso_ms(p['time'])}. "
                f"USGS PAGER alert: {facts['alert_level'] or 'none issued'}. "
                f"Tsunami flag: {'yes' if facts['tsunami_flag'] else 'no'}. Review status: {p.get('status')}.")
        docs.append(Doc("usgs", f["id"], "earthquake", p.get("title") or text[:80], text, _iso_ms(p["time"]),
                        _iso_ms(p.get("updated")), lat, lon, (p.get("place") or "").split(", ")[-1] or None,
                        p.get("url", ""), facts))
    return docs


def normalize_gdacs(raw: dict) -> list[Doc]:
    docs = []
    for f in raw.get("features", []):
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        sev = p.get("severitydata") or {}
        alert = (p.get("alertlevel") or "").lower() or None
        facts = {"alert_level": alert, "alert_score": p.get("alertscore"), "severity": sev.get("severity"),
                 "severity_text": sev.get("severitytext"), "event_type": p.get("eventtype")}
        hazard = GDACS_HAZARD.get(p.get("eventtype"), "other")
        if hazard == "earthquake" and sev.get("severity") is not None:
            facts["magnitude"] = round(float(sev["severity"]), 1)
        text = (f"{p.get('name')}. GDACS alert level {alert or 'not set'} (score {p.get('alertscore')}). "
                f"{sev.get('severitytext') or ''} From {_iso(p.get('fromdate'))} to {_iso(p.get('todate'))}. "
                f"Country: {p.get('country') or 'unspecified'}.")
        docs.append(Doc("gdacs", f"{p.get('eventtype')}-{p.get('eventid')}-{p.get('episodeid')}", hazard,
                        p.get("name") or "GDACS event", text, _iso(p.get("fromdate")), _iso(p.get("datemodified")),
                        lat, lon, p.get("country") or None, (p.get("url") or {}).get("report", ""), facts))
    return docs


def normalize_eonet(raw: dict) -> list[Doc]:
    docs = []
    for e in raw.get("events", []):
        if not e.get("geometry"):
            continue
        g = e["geometry"][-1]
        coords = g["coordinates"]
        if g.get("type") == "Polygon":
            ring = coords[0]
            coords = [sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring)]
        cat = (e.get("categories") or [{}])[0]
        facts = {"category": cat.get("title")}
        if g.get("magnitudeValue") is not None:
            facts["magnitude_value"] = g["magnitudeValue"]
            facts["magnitude_unit"] = g.get("magnitudeUnit")
        text = (f"{e['title']}. Category: {cat.get('title')}. Latest observation {_iso(g.get('date'))} at "
                f"{coords[1]:.2f}, {coords[0]:.2f}." +
                (f" Measured {g['magnitudeValue']} {g.get('magnitudeUnit')}." if g.get("magnitudeValue") else "") +
                f" Tracked since {_iso(e['geometry'][0].get('date'))} ({len(e['geometry'])} observations).")
        src = (e.get("sources") or [{}])[0]
        docs.append(Doc("eonet", e["id"], EONET_HAZARD.get(cat.get("id"), "other"), e["title"], text,
                        _iso(e["geometry"][0].get("date")), _iso(g.get("date")), coords[1], coords[0], None,
                        src.get("url") or e.get("link", ""), facts))
    return docs


def normalize_nws(raw: dict) -> list[Doc]:
    docs = []
    for f in raw.get("features", []):
        p = f["properties"]
        lat = lon = None
        geom = f.get("geometry")
        if geom and geom.get("type") == "Polygon":
            ring = geom["coordinates"][0]
            lon, lat = sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring)
        facts = {"event": p.get("event"), "severity": p.get("severity"), "urgency": p.get("urgency"),
                 "certainty": p.get("certainty"), "expires": _iso(p.get("expires") or p.get("ends")),
                 "area": p.get("areaDesc")}
        description = " ".join((p.get("description") or "").split())[:700]
        text = (f"{p.get('headline') or p.get('event')}. Severity {p.get('severity')}, urgency {p.get('urgency')}, "
                f"certainty {p.get('certainty')}. Areas: {p.get('areaDesc')}. Expires {facts['expires']}. "
                f"Issuer text (verbatim): \"{description}\"")
        docs.append(Doc("nws", p["id"].rsplit("/", 1)[-1], "severe_weather", p.get("event") or "NWS alert", text,
                        _iso(p.get("effective") or p.get("sent")), _iso(p.get("sent")), lat, lon, "United States",
                        p.get("@id") or p["id"], facts))
    return docs


NORMALIZERS = {"usgs": normalize_usgs, "gdacs": normalize_gdacs, "eonet": normalize_eonet, "nws": normalize_nws}


def load_snapshot(folder: Path) -> list[Doc]:
    docs: list[Doc] = []
    for source, fn in NORMALIZERS.items():
        path = folder / f"{source}.json"
        if path.exists():
            docs.extend(fn(json.loads(path.read_text())))
    return docs
