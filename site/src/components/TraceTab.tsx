import { useState } from "react";
import { X } from "@phosphor-icons/react";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import type { FeedStatus } from "../lib/feeds";
import type { Verification } from "../lib/brief";
import type { ModelState } from "../ai/useModel";
import { useT } from "../i18n";

export type TraceEntry =
  | { kind: "feeds"; at: string; status: FeedStatus[] }
  | { kind: "brief"; at: string; incident: string; prompt: string; raw: string; removed: { doc: string; sentence: string }[]; check: Verification; ms: number; device: string; model: string }
  | { kind: "error"; at: string; message: string };

/** Secondary: a side tab with everything the agent did. The product is the map and the briefing. */
export function TraceTab({ entries, model }: { entries: TraceEntry[]; model: ModelState }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();
  return (
    <>
      <button onClick={() => setOpen(true)} aria-expanded={open}
        className="fixed right-0 top-1/2 z-30 origin-bottom-right -translate-y-1/2 -rotate-90 rounded-t-xl border border-b-0 border-line bg-panel px-4 py-2 text-sm text-muted hover:text-ink">
        {t.trace}{entries.some((e) => e.kind === "brief") ? ` (${entries.filter((e) => e.kind === "brief").length})` : ""}
      </button>
      <AnimatePresence>
        {open && (
          <motion.aside role="dialog" aria-label={t.traceTitle}
            initial={reduce ? false : { x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 260, damping: 30 }}
            className="fixed inset-y-0 right-0 z-40 w-full max-w-lg overflow-y-auto border-l border-line bg-panel p-6 shadow-2xl">
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-lg font-semibold">{t.traceTitle}</h2>
              <button onClick={() => setOpen(false)} className="rounded-full border border-line p-1.5" aria-label={t.close}><X size={16} /></button>
            </div>
            <p className="mb-4 text-xs text-muted">model: {model.phase === "ready" ? `${model.model} (${model.device})` : model.phase}</p>
            {!entries.some((e) => e.kind === "brief") && <p className="mb-6 text-sm text-muted">{t.traceEmpty}</p>}
            <div className="space-y-6 text-sm">
              {entries.map((e, i) => (
                <section key={i} className="rounded-2xl border border-line p-4">
                  <p className="mb-2 text-xs text-muted">{new Date(e.at).toLocaleTimeString()} · {e.kind}</p>
                  {e.kind === "feeds" && (
                    <>
                      <p className="mb-2 font-medium">{t.traceFeeds}</p>
                      <ul className="space-y-1 font-mono text-xs">{e.status.map((s) => <li key={s.source}>{s.source} {s.ok ? `200 · ${s.count} docs · ${s.ms} ms` : `failed · ${s.error}`}</li>)}</ul>
                    </>
                  )}
                  {e.kind === "error" && <p className="text-red">{e.message}</p>}
                  {e.kind === "brief" && (
                    <>
                      <p className="font-medium">{e.incident}</p>
                      <p className="mb-3 text-xs text-muted">{e.model} on {e.device}, {e.ms} ms</p>
                      {e.removed.length > 0 && (
                        <details className="mb-2"><summary className="cursor-pointer">{t.traceRemoved} ({e.removed.length})</summary>
                          <ul className="mt-1 text-xs text-muted">{e.removed.map((r, j) => <li key={j}>{r.doc}: {r.sentence}</li>)}</ul></details>
                      )}
                      <details className="mb-2"><summary className="cursor-pointer">{t.tracePrompt}</summary><pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap text-xs text-muted">{e.prompt}</pre></details>
                      <details className="mb-2" open><summary className="cursor-pointer">{t.traceRaw}</summary><pre className="mt-1 whitespace-pre-wrap text-xs">{e.raw}</pre></details>
                      <p className="mt-2 font-medium">{t.traceChecks}</p>
                      <ul className="mt-1 space-y-1 text-xs">
                        <li>alert: {e.check.alertOk ? "ok" : `stated vs expected ${e.check.expectedAlert}`}</li>
                        {e.check.facts.map((f, j) => <li key={j}>{f.ok ? "ok" : "rejected"}: {f.text.slice(0, 80)} {f.problems.join("; ")}</li>)}
                      </ul>
                    </>
                  )}
                </section>
              ))}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
}
