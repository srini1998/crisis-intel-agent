// Incident linking, input sanitizing, the deterministic baseline brief and the claim verifier.
// Ported from crisis/link.py, crisis/sanitize.py, crisis/report.py and crisis/verify.py.
import { ALERT_ORDER, type Doc, type Hazard } from "./feeds.ts";

const WINDOWS: Partial<Record<Hazard, [number, number]>> = {
  earthquake: [100, 24], cyclone: [600, 168], wildfire: [40, 336], volcano: [30, 720], flood: [300, 336], drought: [800, 1440],
};

export function haversineKm(a: [number, number], b: [number, number]): number {
  const r = (d: number) => (d * Math.PI) / 180;
  const h = Math.sin(r(b[0] - a[0]) / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(r(b[1] - a[1]) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

function compatible(a: Doc, b: Doc): boolean {
  if (a.source === b.source || a.hazard !== b.hazard || a.hazard === "severe_weather") return false;
  const w = WINDOWS[a.hazard];
  if (!w || a.lat == null || a.lon == null || b.lat == null || b.lon == null) return false;
  if (haversineKm([a.lat, a.lon], [b.lat, b.lon]) > w[0]) return false;
  if (Math.abs(Date.parse(a.time) - Date.parse(b.time)) > w[1] * 3_600_000) return false;
  if (a.hazard === "earthquake") {
    const ma = a.facts.magnitude as number | undefined, mb = b.facts.magnitude as number | undefined;
    if (ma == null || mb == null || Math.abs(ma - mb) > 0.5) return false;
  }
  return true;
}

export type Incident = { id: string; hazard: Hazard; title: string; members: Doc[]; severity: number; sources: string[]; lat: number | null; lon: number | null; time: string };

export function maxAlert(docs: Doc[]): string {
  const lv = docs.map((d) => String(d.facts.alert_level ?? "").toLowerCase()).filter((l) => l in ALERT_ORDER);
  return lv.length ? lv.reduce((a, b) => (ALERT_ORDER[b] > ALERT_ORDER[a] ? b : a)) : "unknown";
}

function severity(m: Doc[]): number {
  let s = 0;
  for (const d of m) {
    const alert = ALERT_ORDER[String(d.facts.alert_level ?? "").toLowerCase()] ?? 0;
    s = Math.max(s, alert * 2);
    if (d.hazard === "earthquake" && typeof d.facts.magnitude === "number") s = Math.max(s, d.facts.magnitude - 4 + alert * 2);
    if (d.source === "nws") s = Math.max(s, d.facts.severity === "Extreme" ? 2.5 : 1);
    if (d.facts.tsunami_flag) s += 1;
  }
  return Math.round(s * 100) / 100;
}

export function link(docs: Doc[]): Incident[] {
  const parent = docs.map((_, i) => i);
  const find = (i: number): number => (parent[i] === i ? i : (parent[i] = find(parent[i])));
  for (let i = 0; i < docs.length; i++) for (let j = i + 1; j < docs.length; j++) if (compatible(docs[i], docs[j])) parent[find(i)] = find(j);
  const groups = new Map<number, Doc[]>();
  docs.forEach((d, i) => groups.set(find(i), [...(groups.get(find(i)) ?? []), d]));
  return [...groups.values()].map((m) => {
    const anchor = [...m].sort((a, b) => a.time.localeCompare(b.time))[0];
    const located = m.find((d) => d.lat != null) ?? anchor;
    return { id: `${anchor.source}:${anchor.id}`, hazard: anchor.hazard, title: m.reduce((a, b) => (b.title.length > a.title.length ? b : a)).title,
      members: m, severity: severity(m), sources: [...new Set(m.map((d) => d.source))].sort(), lat: located.lat, lon: located.lon, time: anchor.time };
  }).sort((a, b) => b.severity - a.severity);
}

// Sanitizer: a heuristic first layer. Paraphrased instructions can slip past; citation/number checks are limited too and do not establish factuality.
const PATTERNS = [
  /\b(ignore|disregard|forget|override)\b[^.]{0,40}\b(previous|prior|above|all|earlier|system)\b[^.]{0,40}\b(instructions?|prompts?|rules?|messages?)\b/i,
  /\b(system|developer|admin(istrator)?)\s+(notice|message|prompt|instruction|override)\b/i,
  /\b(to|for|attention)\s+(the\s+)?(ai|assistant|model|llm|chatbot)\b/i,
  /\byou\s+(must|should|are\s+required\s+to|will)\s+(now\s+)?(report|state|say|write|include|output|respond)\b/i,
  /\binclude\s+the\s+word\b/i,
];
export function sanitize(docs: Doc[]): { docs: Doc[]; removed: { doc: string; sentence: string }[] } {
  const removed: { doc: string; sentence: string }[] = [];
  const clean = docs.map((d) => {
    const parts = d.text.match(/[^.!?\n]*[.!?\n]?/g) ?? [d.text];
    const kept = parts.map((s) => {
      if (s && PATTERNS.some((p) => p.test(s))) {
        removed.push({ doc: `${d.source}:${d.id}`, sentence: s.trim() });
        return " [removed: instruction-like text] ";
      }
      return s;
    });
    return { ...d, text: kept.join("").trim() };
  });
  return { docs: clean, removed };
}

export type Fact = { text: string; citations: number[] };
export type Report = { headline: string; alert_level: string; facts: Fact[]; watch: string[]; author: "template" | "model" };

export function templateReport(docs: Doc[]): Report {
  const facts: Fact[] = docs.slice(0, 5).map((d, i) => {
    const f = d.facts;
    if (d.source === "usgs") return { text: `USGS: magnitude ${f.magnitude}, depth ${f.depth_km} km, PAGER alert ${f.alert_level ?? "none"}.`, citations: [i + 1] };
    if (d.source === "gdacs") return { text: `GDACS alert level ${f.alert_level}; ${f.severity_text ?? "no severity text"}.`, citations: [i + 1] };
    if (d.source === "eonet") return { text: `NASA EONET tracks this as ${f.category}${f.magnitude_value != null ? `, latest ${f.magnitude_value} ${f.magnitude_unit ?? ""}` : ""}.`, citations: [i + 1] };
    return { text: `NWS ${f.event}: severity ${f.severity}, urgency ${f.urgency}, expires ${f.expires}.`, citations: [i + 1] };
  });
  const lead = docs.reduce((a, b) => (b.title.length > a.title.length ? b : a));
  return { headline: lead.title, alert_level: maxAlert(docs), facts, watch: ["Updates from the cited publishers."], author: "template" };
}

const NUM = /(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?/g;
const CITE = /\[\s*\d+(?:\s*,\s*\d+)*\s*\]/g;
// Numbers fused to a name by a hyphen ("CHAMPI-26", "COVID-19") are part of an identifier, not a claim.
const IDENT = /\b[A-Za-z]{2,}-\d+\b/g;
export const numbersIn = (t: string) => (t.replace(CITE, " ").replace(IDENT, " ").match(NUM) ?? []).map((m) => Number(m.replace(/,/g, "")));
const haystack = (d: Doc) => [d.title, d.text, d.time, JSON.stringify(d.facts)].join(" ");

export type CheckedFact = Fact & { ok: boolean; problems: string[] };
export type Verification = { facts: CheckedFact[]; alertOk: boolean; expectedAlert: string; factualVerification: "not_established"; passed: boolean };

export function verify(r: Report, docs: Doc[]): Verification {
  const facts = r.facts.map((f) => {
    const problems: string[] = [];
    const valid = f.citations.filter((c) => Number.isInteger(c) && c >= 1 && c <= docs.length);
    if (!f.citations.length) problems.push("no citation");
    if (valid.length !== f.citations.length) problems.push("cites a document that does not exist");
    const cited = valid.map((c) => docs[c - 1]);
    const unsupported = numbersIn(f.text).filter((n) => !cited.some((d) => numbersIn(haystack(d)).some((m) => Math.abs(m - n) <= (Number.isInteger(n) && Number.isInteger(m) ? 0 : 0.051))));
    if (unsupported.length) problems.push(`numbers not in the cited source: ${unsupported.join(", ")}`);
    return { ...f, ok: !problems.length, problems };
  });
  const expectedAlert = maxAlert(docs);
  const alertOk = r.alert_level === expectedAlert;
  return { facts, alertOk, expectedAlert, factualVerification: "not_established", passed: facts.length > 0 && facts.every((f) => f.ok) && alertOk };
}

/** Parse the small model's line format: HEADLINE:, FACT: ... [n], ALERT:, WATCH: */
export function parseModelReport(raw: string): Report {
  const lines = raw.split("\n").map((l) => l.trim()).filter(Boolean);
  const get = (k: string) => lines.find((l) => l.toUpperCase().startsWith(k))?.slice(k.length).trim().replace(/^[:\s-]+/, "") ?? "";
  const facts = lines.filter((l) => /^FACT\b/i.test(l)).map((l) => {
    const body = l.replace(/^FACT\s*[:\-]?\s*/i, "");
    const citations = [...body.matchAll(/\[(\d+(?:\s*,\s*\d+)*)\]/g)].flatMap((m) => m[1].split(",").map((x) => Number(x.trim())));
    return { text: body.replace(CITE, "").trim(), citations };
  }).slice(0, 5);
  const alert = get("ALERT").toLowerCase().match(/green|yellow|orange|red|unknown/)?.[0] ?? "unknown";
  return { headline: get("HEADLINE") || "Untitled briefing", alert_level: alert, facts, watch: lines.filter((l) => /^WATCH\b/i.test(l)).map((l) => l.replace(/^WATCH\s*[:\-]?\s*/i, "")).slice(0, 3), author: "model" };
}

export function renderDocs(docs: Doc[]): string {
  return docs.map((d, i) => `[${i + 1}] source=${d.source} time=${d.time}\ntitle: ${d.title}\nfacts: ${JSON.stringify(Object.fromEntries(Object.entries(d.facts).filter(([, v]) => v !== null && v !== "")))}\ntext: ${d.text}`).join("\n\n");
}

/** Compact one-line-per-document form for small models: the facts that matter, nothing else. */
export function compactDocs(docs: Doc[]): string {
  return docs.map((d, i) => {
    const f = Object.entries(d.facts).filter(([, v]) => v !== null && v !== "" && v !== false).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join("; ");
    return `[${i + 1}] ${d.source.toUpperCase()}: ${d.title}. ${f}.`;
  }).join("\n");
}
