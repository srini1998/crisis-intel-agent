import { useEffect, useMemo, useState } from "react";
import { ArrowClockwise, CloudLightning, Drop, Fire, Mountains, Waveform, Snowflake, Sun, Warning } from "@phosphor-icons/react";
import type { Incident } from "../lib/brief";
import { maxAlert } from "../lib/brief";
import type { FeedStatus } from "../lib/feeds";
import { useT } from "../i18n";
import { IncidentMap } from "./IncidentMap";
import { BriefPanel } from "./BriefPanel";
import type { TraceEntry } from "./TraceTab";
import type { useModel } from "../ai/useModel";

export const HAZARD_ICON: Record<string, typeof Waveform> = { earthquake: Waveform, cyclone: CloudLightning, wildfire: Fire, volcano: Mountains, flood: Drop, drought: Sun, severe_weather: Warning, ice: Snowflake, other: Warning };
const DOT: Record<string, string> = { red: "bg-red", orange: "bg-orange", yellow: "bg-yellow", green: "bg-green", unknown: "bg-muted" };

type Props = { incidents: Incident[]; loading: boolean; status: FeedStatus[]; fetchedAt: string; onRefresh: () => void; model: ReturnType<typeof useModel>; onTrace: (e: TraceEntry) => void };

export function LiveDesk({ incidents, loading, status, fetchedAt, onRefresh, model, onTrace }: Props) {
  const { t, lang } = useT();
  const [hazard, setHazard] = useState<string>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const hazards = useMemo(() => [...new Set(incidents.map((i) => i.hazard))], [incidents]);
  const shown = useMemo(() => incidents.filter((i) => hazard === "all" || i.hazard === hazard), [incidents, hazard]);
  useEffect(() => {
    if (!selected && shown.length) setSelected(shown[0].id);
  }, [shown, selected]);
  const current = incidents.find((i) => i.id === selected) ?? null;
  const time = fetchedAt ? new Date(fetchedAt).toLocaleTimeString(lang === "ja" ? "ja-JP" : "en-US", { hour: "2-digit", minute: "2-digit" }) : "";

  return (
    <section id="live" className="mx-auto max-w-7xl scroll-mt-24 px-4 py-24 md:px-8 md:py-32">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t.liveTitle}</h2>
        <div className="flex items-center gap-3 text-sm text-muted">
          {time && <span>{t.updated(time)}</span>}
          <button onClick={onRefresh} className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 hover:border-signal active:scale-[0.98]">
            <ArrowClockwise size={14} aria-hidden /> {t.refresh}
          </button>
        </div>
      </div>

      <div className="mb-6 flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="Hazard filter">
        {["all", ...hazards].map((h) => (
          <button key={h} role="tab" aria-selected={hazard === h} onClick={() => setHazard(h)}
            className={`shrink-0 rounded-full border px-4 py-1.5 text-sm transition-colors ${hazard === h ? "border-signal bg-signal text-white" : "border-line text-muted hover:text-ink"}`}>
            {h === "all" ? t.filterAll : t.hazards[h] ?? h} <span className="opacity-70">{h === "all" ? incidents.length : incidents.filter((i) => i.hazard === h).length}</span>
          </button>
        ))}
      </div>

      {status.some((s) => !s.ok) && (
        <p className="mb-4 text-sm text-muted">{status.filter((s) => !s.ok).map((s) => `${s.source.toUpperCase()} ${t.feedFailed}`).join(" / ")}</p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.35fr_1fr]">
        <div className="min-w-0">
          {loading ? (
            <div className="flex h-[420px] items-center justify-center rounded-3xl border border-line bg-panel text-muted md:h-[520px]">{t.loading}</div>
          ) : (
            <IncidentMap incidents={shown} selected={selected} onSelect={setSelected} />
          )}
          <ul className="mt-4 grid max-h-[360px] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2" aria-label="Incidents">
            {loading && Array.from({ length: 6 }).map((_, i) => <li key={i} className="h-16 animate-pulse rounded-2xl bg-panel" />)}
            {shown.slice(0, 60).map((i) => {
              const Icon = HAZARD_ICON[i.hazard] ?? Warning;
              const level = maxAlert(i.members);
              return (
                <li key={i.id}>
                  <button onClick={() => setSelected(i.id)} aria-pressed={selected === i.id}
                    className={`flex w-full items-start gap-3 rounded-2xl border p-3 text-left transition-colors ${selected === i.id ? "border-signal bg-panel" : "border-line hover:bg-panel"}`}>
                    <Icon size={20} className="mt-0.5 shrink-0 text-muted" aria-hidden />
                    <span className="min-w-0">
                      <span className="line-clamp-1 text-sm font-medium">{i.title}</span>
                      <span className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                        {level !== "unknown" && <span className={`inline-block h-2 w-2 rounded-full ${DOT[level]}`} aria-label={`${level} alert`} />}
                        {t.sourcesCount(i.sources.length)}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
        <BriefPanel incident={current} model={model} onTrace={onTrace} />
      </div>
    </section>
  );
}
