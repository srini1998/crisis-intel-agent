import { useEffect, useMemo, useState } from "react";
import {
  compactDocs,
  parseModelReport,
  sanitize,
  templateReport,
  verify,
  type Incident,
  type Report,
  type Verification,
} from "../lib/brief";
import { cloudGenerate, cloudStatus } from "../ai/cloud";
import { useT } from "../i18n";
import type { TraceEntry } from "./TraceTab";
export function BriefPanel({
  incident,
  onTrace,
}: {
  incident: Incident | null;
  onTrace: (e: TraceEntry) => void;
}) {
  const { t } = useT();
  const [copied, setCopied] = useState("");
  const [cloud, setCloud] = useState<{ enabled: boolean; model?: string } | null>(null);
  const [ai, setAi] = useState<{
    id: string;
    report?: Report;
    check?: Verification;
    model?: string;
    ms?: number;
    removed?: number;
    error?: string;
    busy?: boolean;
  } | null>(null);
  useEffect(() => {
    cloudStatus().then(setCloud);
  }, []);
  async function writeWithAi() {
    if (!incident) return;
    const id = incident.id;
    setAi({ id, busy: true });
    // Agency text is untrusted: strip instruction-like sentences before it reaches the model.
    const { docs, removed } = sanitize(incident.members);
    const prompt = `Numbered official reports:\n${compactDocs(docs)}\n\nWrite a short travel brief in exactly this line format:\nHEADLINE: <one line>\nFACT: <one fact from one report, with its number copied exactly> [n]\n(2 to 4 FACT lines, each ending with the report number in brackets)\nALERT: <green|yellow|orange|red|unknown — the highest publisher alert level given>\nWATCH: <one thing a traveller should check with the publisher>\nUse only the reports. No advice beyond them.`;
    try {
      const r = await cloudGenerate(prompt, 320);
      const report = parseModelReport(r.text);
      const check = verify(report, docs);
      setAi({ id, report, check, model: r.model, ms: r.ms, removed: removed.length });
      onTrace({
        kind: "brief",
        at: new Date().toISOString(),
        incident: incident.title,
        prompt,
        raw: r.text,
        removed,
        ms: r.ms,
        device: "cloud (Groq free plan)",
        model: r.model,
        check,
      });
    } catch (e) {
      setAi({ id, error: e instanceof Error ? e.message : String(e) });
    }
  }
  const report = useMemo(
    () => (incident ? templateReport(incident.members) : null),
    [incident],
  );
  const check = useMemo(
    () => (incident && report ? verify(report, incident.members) : null),
    [incident, report],
  );
  if (!incident || !report || !check)
    return (
      <aside className="flex min-h-[320px] items-center justify-center rounded-3xl border border-line bg-panel p-6 text-muted">
        {t.pick}
      </aside>
    );
  async function copy() {
    if (!incident || !report || !check) return;
    try {
      await navigator.clipboard.writeText(
        [
          report.headline,
          ...report.facts.map((f) => f.text),
          ...incident.members.map((d) => d.url),
        ].join("\n"),
      );
      setCopied(incident.id);
      onTrace({
        kind: "brief",
        at: new Date().toISOString(),
        incident: incident.title,
        prompt: JSON.stringify(incident.members),
        raw: JSON.stringify(report),
        removed: [],
        ms: 0,
        device: "browser",
        model: "none / deterministic source template",
        check,
      });
    } catch {
      setCopied("error");
    }
  }
  return (
    <aside className="flex min-w-0 flex-col rounded-3xl border border-line bg-panel p-5 md:p-6 lg:sticky lg:top-24 lg:self-start">
      <p className="mb-3 text-xs uppercase tracking-widest text-signal">
        Your source brief / No download needed
      </p>
      <h3 className="text-2xl font-semibold leading-snug">{report.headline}</h3>
      <p className="mt-3 text-sm text-muted">
        These are published reports, not a prediction. Read each source for its
        time, location and official advice.
      </p>
      <p className="mt-3 text-sm">
        Publisher alert level: <b>{report.alert_level}</b>
      </p>
      <ul className="mt-5 space-y-3">
        {check.facts
          .filter((f) => f.ok)
          .map((f, i) => (
            <li key={i} className="text-sm leading-relaxed">
              {f.text}{" "}
              <sup className="text-signal">
                {f.citations.map((n) => (
                  <a key={n} href={"#source-" + incident.id + "-" + n}>
                    {" "}
                    [{n}]
                  </a>
                ))}
              </sup>
            </li>
          ))}
      </ul>
      <button
        onClick={copy}
        className="mt-5 self-start rounded-full border border-line px-4 py-2 text-sm"
      >
        {copied === incident.id
          ? "Copied with sources ✓"
          : "Copy brief with sources"}
      </button>
      {copied === "error" && (
        <p role="status">Clipboard unavailable. Select and copy the brief.</p>
      )}
      <div className="mt-6 border-t border-line pt-4" aria-live="polite">
        <h4 className="text-sm font-medium">
          Optional: plain-language brief by a cloud AI agent
        </h4>
        <p className="mt-2 text-xs text-muted">
          The agent rewrites these reports in plain language. Code then checks
          every sentence: it must cite a real report, every number must appear
          in the report it cites, and the alert level must match the
          publishers’. Checks catch inconsistencies; they do not prove truth.
        </p>
        <button
          onClick={writeWithAi}
          disabled={!cloud?.enabled || (ai?.busy && ai.id === incident.id)}
          className="mt-3 rounded-full border border-line px-4 py-2 text-sm disabled:opacity-50"
        >
          {ai?.busy && ai.id === incident.id ? "Writing and checking…" : "Write a checked AI brief"}
        </button>
        {cloud && !cloud.enabled && (
          <p className="mt-2 text-xs text-muted">
            Cloud AI is not connected here. The source brief above needs no AI.
          </p>
        )}
        {ai?.id === incident.id && ai.error && (
          <p role="alert" className="mt-2 text-sm">{ai.error}</p>
        )}
        {ai?.id === incident.id && ai.report && ai.check && (
          <div className="mt-3 rounded-2xl border border-line p-4">
            <p className="font-medium">{ai.report.headline}</p>
            <ul className="mt-2 space-y-2">
              {ai.check.facts.map((f, i) => (
                <li key={i} className="text-sm">
                  <span aria-hidden="true">{f.ok ? "✓ " : "✗ "}</span>
                  <span className={f.ok ? "" : "line-through opacity-70"}>{f.text}</span>{" "}
                  <sup className="text-signal">[{f.citations.join(", ")}]</sup>
                  {!f.ok && (
                    <span className="block text-xs">Rejected: {f.problems.join("; ")}</span>
                  )}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-sm">
              {ai.check.alertOk ? "✓" : "✗"} Alert level {ai.report.alert_level}
              {ai.check.alertOk ? " matches the publishers" : ` — publishers say ${ai.check.expectedAlert}`}
            </p>
            <p className="mt-2 text-sm font-medium">
              {ai.check.passed
                ? "Passed citation, number and alert checks."
                : "Did not pass every check — rely on the source brief above."}
            </p>
            <p className="mt-2 text-xs text-muted">
              {ai.model} on Groq’s free plan · {ai.ms} ms
              {ai.removed ? ` · ${ai.removed} instruction-like sentence(s) removed before sending` : ""}.
              Factual truth is not established by these checks.
            </p>
          </div>
        )}
      </div>
      <div className="mt-6 border-t border-line pt-4">
        <h4 className="text-sm font-medium">Read the original reports</h4>
        <ol className="mt-3 space-y-3">
          {incident.members.map((d, i) => (
            <li
              id={"source-" + incident.id + "-" + (i + 1)}
              key={d.id}
              className="text-sm"
            >
              <a
                href={d.url}
                target="_blank"
                rel="noreferrer"
                className="hover:text-signal"
              >
                [{i + 1}] {d.source.toUpperCase()}: {d.title} ↗
              </a>
            </li>
          ))}
        </ol>
      </div>
      <details className="mt-6 text-xs text-muted">
        <summary className="cursor-pointer">How this brief is built</summary>
        <p className="mt-2">
          A deterministic template reads the agencies’ fields. Citation, number
          and alert checks catch inconsistencies; they do not establish truth or
          cover every hazard. The optional AI brief below runs only when you ask, on Groq’s free plan through a server function, and is checked the same way.
        </p>
      </details>
    </aside>
  );
}
