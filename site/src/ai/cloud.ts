// Optional server-side cloud model (Groq free plan via /api/generate). No key in the browser.
export async function cloudStatus(): Promise<{ enabled: boolean; model?: string }> {
  try {
    const r = await fetch("/api/generate", { signal: AbortSignal.timeout(8000) });
    if (!r.ok) return { enabled: false };
    return await r.json();
  } catch {
    return { enabled: false };
  }
}
export async function cloudGenerate(prompt: string, maxTokens: number) {
  const started = performance.now();
  const r = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: prompt }], maxTokens }),
    signal: AbortSignal.timeout(45000),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Cloud generation unavailable.");
  return { text: String(data.text), model: String(data.model), ms: Math.round(performance.now() - started) };
}
