import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAll, type Doc, type FeedStatus } from "./lib/feeds";
import { link, type Incident } from "./lib/brief";
import { useModel } from "./ai/useModel";
import { Nav } from "./components/Nav";
import { Hero } from "./components/Hero";
import { LiveDesk } from "./components/LiveDesk";
import { HowItWorks } from "./components/HowItWorks";
import { SourcesFooter } from "./components/SourcesFooter";
import { TraceTab, type TraceEntry } from "./components/TraceTab";

export function App() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [status, setStatus] = useState<FeedStatus[]>([]);
  const [fetchedAt, setFetchedAt] = useState<string>("");
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const model = useModel();

  const refresh = useCallback(async () => {
    setDocs(null);
    const r = await fetchAll();
    setDocs(r.docs);
    setStatus(r.status);
    setFetchedAt(r.fetchedAt);
    setTrace((t) => [{ kind: "feeds", at: r.fetchedAt, status: r.status }, ...t.filter((x) => x.kind !== "feeds")]);
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const incidents: Incident[] = useMemo(() => (docs ? link(docs) : []), [docs]);
  const addTrace = useCallback((e: TraceEntry) => setTrace((t) => [e, ...t]), []);

  return (
    <main className="w-full max-w-full overflow-x-hidden">
      <Nav />
      <Hero />
      <LiveDesk incidents={incidents} loading={docs === null} status={status} fetchedAt={fetchedAt} onRefresh={refresh} model={model} onTrace={addTrace} />
      <HowItWorks />
      <SourcesFooter status={status} />
      <TraceTab entries={trace} model={model.state} />
    </main>
  );
}
