import { useMemo, useState } from "react";
import { templateReport, verify, type Incident } from "../lib/brief";
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
          cover every hazard. No generative model is running.
        </p>
      </details>
    </aside>
  );
}
