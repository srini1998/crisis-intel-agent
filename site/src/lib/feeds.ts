// Live official feeds, fetched straight from the publishers by the visitor's browser (all four send
// Access-Control-Allow-Origin: *). Same normalization as crisis/sources.py in this repository.

export type Hazard = "earthquake" | "cyclone" | "flood" | "volcano" | "wildfire" | "drought" | "severe_weather" | "ice" | "other";
export type Source = "usgs" | "gdacs" | "eonet" | "nws";

export type Doc = {
  source: Source;
  id: string;
  hazard: Hazard;
  title: string;
  text: string;
  time: string;
  lat: number | null;
  lon: number | null;
  country: string | null;
  url: string;
  facts: Record<string, string | number | boolean | null>;
};

export const ALERT_ORDER: Record<string, number> = { green: 1, yellow: 2, orange: 3, red: 4 };

const FEEDS: Record<Source, string> = {
  usgs: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
  gdacs: "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP",
  eonet: "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=14",
  nws: "https://api.weather.gov/alerts/active?severity=Extreme,Severe",
};

const GDACS_HAZARD: Record<string, Hazard> = { EQ: "earthquake", TC: "cyclone", FL: "flood", VO: "volcano", WF: "wildfire", DR: "drought" };
const EONET_HAZARD: Record<string, Hazard> = { wildfires: "wildfire", volcanoes: "volcano", severeStorms: "cyclone", floods: "flood", earthquakes: "earthquake", drought: "drought", seaLakeIce: "ice" };

const iso = (v: string | number | null | undefined): string => {
  if (v === null || v === undefined || v === "") return "";
  const d = typeof v === "number" ? new Date(v) : new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString().replace(/\.\d{3}Z$/, "Z");
};
const round1 = (n: number) => Math.round(n * 10) / 10;

function usgs(raw: any): Doc[] {
  return (raw.features ?? []).filter((f: any) => f.properties?.type === "earthquake" && f.properties?.mag != null).map((f: any) => {
    const p = f.properties;
    const [lon, lat, depth] = f.geometry.coordinates;
    const mag = round1(Number(p.mag));
    const facts = { magnitude: mag, depth_km: round1(Number(depth)), tsunami_flag: Boolean(p.tsunami), felt_reports: p.felt ?? null, alert_level: p.alert ?? null };
    const text = `Magnitude ${mag} earthquake, ${p.place ?? "location not named"}, depth ${facts.depth_km} km, at ${iso(p.time)}. ` +
      `USGS PAGER alert: ${p.alert ?? "none issued"}. Tsunami flag: ${p.tsunami ? "yes" : "no"}.`;
    return { source: "usgs", id: f.id, hazard: "earthquake", title: p.title ?? text.slice(0, 80), text, time: iso(p.time), lat, lon,
      country: String(p.place ?? "").split(", ").pop() || null, url: p.url ?? "", facts } satisfies Doc;
  });
}

function gdacs(raw: any): Doc[] {
  return (raw.features ?? []).map((f: any) => {
    const p = f.properties;
    const [lon, lat] = f.geometry.coordinates;
    const sev = p.severitydata ?? {};
    const alert = (p.alertlevel ?? "").toLowerCase() || null;
    const hazard = GDACS_HAZARD[p.eventtype] ?? "other";
    const facts: Doc["facts"] = { alert_level: alert, severity_text: sev.severitytext ?? null };
    if (hazard === "earthquake" && sev.severity != null) facts.magnitude = round1(Number(sev.severity));
    const text = `${p.name}. GDACS alert level ${alert ?? "not set"}. ${sev.severitytext ?? ""} From ${iso(p.fromdate)} to ${iso(p.todate)}. Country: ${p.country || "unspecified"}.`;
    return { source: "gdacs", id: `${p.eventtype}-${p.eventid}-${p.episodeid}`, hazard, title: p.name ?? "GDACS event", text, time: iso(p.fromdate), lat, lon,
      country: p.country || null, url: p.url?.report ?? "", facts } satisfies Doc;
  });
}

function eonet(raw: any): Doc[] {
  return (raw.events ?? []).filter((e: any) => e.geometry?.length).map((e: any) => {
    const g = e.geometry[e.geometry.length - 1];
    let c = g.coordinates;
    if (g.type === "Polygon") {
      const ring = c[0];
      c = [ring.reduce((s: number, x: number[]) => s + x[0], 0) / ring.length, ring.reduce((s: number, x: number[]) => s + x[1], 0) / ring.length];
    }
    const cat = e.categories?.[0] ?? {};
    const facts: Doc["facts"] = { category: cat.title ?? null };
    if (g.magnitudeValue != null) {
      facts.magnitude_value = g.magnitudeValue;
      facts.magnitude_unit = g.magnitudeUnit ?? null;
    }
    const text = `${e.title}. Category: ${cat.title}. Latest observation ${iso(g.date)} at ${c[1].toFixed(2)}, ${c[0].toFixed(2)}.` +
      (g.magnitudeValue != null ? ` Measured ${g.magnitudeValue} ${g.magnitudeUnit ?? ""}.` : "") + ` Tracked since ${iso(e.geometry[0].date)}.`;
    return { source: "eonet", id: e.id, hazard: EONET_HAZARD[cat.id] ?? "other", title: e.title, text, time: iso(e.geometry[0].date), lat: c[1], lon: c[0],
      country: null, url: e.sources?.[0]?.url ?? e.link ?? "", facts } satisfies Doc;
  });
}

function nws(raw: any): Doc[] {
  return (raw.features ?? []).map((f: any) => {
    const p = f.properties;
    let lat: number | null = null, lon: number | null = null;
    if (f.geometry?.type === "Polygon") {
      const ring = f.geometry.coordinates[0];
      lon = ring.reduce((s: number, x: number[]) => s + x[0], 0) / ring.length;
      lat = ring.reduce((s: number, x: number[]) => s + x[1], 0) / ring.length;
    }
    const facts = { event: p.event ?? null, severity: p.severity ?? null, urgency: p.urgency ?? null, expires: iso(p.expires ?? p.ends), area: p.areaDesc ?? null };
    const desc = String(p.description ?? "").replace(/\s+/g, " ").slice(0, 600);
    const text = `${p.headline ?? p.event}. Severity ${p.severity}, urgency ${p.urgency}. Areas: ${p.areaDesc}. Expires ${facts.expires}. Issuer text (verbatim): "${desc}"`;
    return { source: "nws", id: String(p.id).split("/").pop()!, hazard: "severe_weather", title: p.event ?? "NWS alert", text, time: iso(p.effective ?? p.sent), lat, lon,
      country: "United States", url: p["@id"] ?? p.id, facts } satisfies Doc;
  });
}

const NORMALIZE: Record<Source, (raw: any) => Doc[]> = { usgs, gdacs, eonet, nws };

export type FeedStatus = { source: Source; ok: boolean; count: number; error?: string; ms: number };

export async function fetchAll(): Promise<{ docs: Doc[]; status: FeedStatus[]; fetchedAt: string }> {
  const results = await Promise.all((Object.keys(FEEDS) as Source[]).map(async (source) => {
    const t0 = performance.now();
    try {
      const r = await fetch(FEEDS[source], { headers: { Accept: "application/geo+json, application/json" }, signal: AbortSignal.timeout(20_000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const docs = NORMALIZE[source](await r.json());
      return { docs, status: { source, ok: true, count: docs.length, ms: Math.round(performance.now() - t0) } };
    } catch (e) {
      return { docs: [], status: { source, ok: false, count: 0, error: (e as Error).message, ms: Math.round(performance.now() - t0) } };
    }
  }));
  return { docs: results.flatMap((r) => r.docs), status: results.map((r) => r.status), fetchedAt: new Date().toISOString() };
}
