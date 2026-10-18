import { useCallback, useEffect, useRef, useState } from "react";

export type ModelState =
  | { phase: "idle" }
  | { phase: "loading"; loaded: number; total: number }
  | { phase: "ready"; device: string; model: string }
  | { phase: "error"; message: string };

/** One shared worker per page. The model only downloads after the visitor asks for it. */
export function useModel() {
  const worker = useRef<Worker | null>(null);
  const [state, setState] = useState<ModelState>({ phase: "idle" });
  const files = useRef<Record<string, { loaded: number; total: number }>>({});
  const pending = useRef<Record<string, { onToken: (c: string) => void; resolve: (r: { text: string; ms: number; device: string; model: string }) => void; reject: (e: Error) => void }>>({});

  const ensure = useCallback(() => {
    if (worker.current) return worker.current;
    const w = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    w.onmessage = (e) => {
      const m = e.data;
      if (m.type === "progress") {
        files.current[m.file] = { loaded: m.loaded ?? 0, total: m.total ?? 0 };
        const all = Object.values(files.current);
        setState({ phase: "loading", loaded: all.reduce((s, f) => s + f.loaded, 0), total: all.reduce((s, f) => s + f.total, 0) });
      } else if (m.type === "ready") setState({ phase: "ready", device: m.device, model: m.model });
      else if (m.type === "token") pending.current[m.id]?.onToken(m.chunk);
      else if (m.type === "done") {
        pending.current[m.id]?.resolve(m);
        delete pending.current[m.id];
      } else if (m.type === "error") {
        if (m.id && pending.current[m.id]) {
          pending.current[m.id].reject(new Error(m.message));
          delete pending.current[m.id];
        } else setState({ phase: "error", message: m.message });
      }
    };
    worker.current = w;
    return w;
  }, []);

  const load = useCallback(() => {
    setState((s) => (s.phase === "ready" ? s : { phase: "loading", loaded: 0, total: 0 }));
    ensure().postMessage({ type: "load" });
  }, [ensure]);

  const generate = useCallback((messages: { role: string; content: string }[], onToken: (c: string) => void, maxTokens = 320, prefill = "") => {
    const id = Math.random().toString(36).slice(2);
    return new Promise<{ text: string; ms: number; device: string; model: string }>((resolve, reject) => {
      pending.current[id] = { onToken, resolve, reject };
      ensure().postMessage({ type: "generate", id, messages, maxTokens, prefill });
    });
  }, [ensure]);

  useEffect(() => () => worker.current?.terminate(), []);
  return { state, load, generate };
}
