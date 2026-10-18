import { createContext, useContext, useEffect, type ReactNode } from "react";
export type Lang = "en" | "ja";
const EN = {
  navLive: "Live map",
  navHow: "How it works",
  navSources: "Sources",
  heroTitle: "Know what’s happening where you’re going.",
  heroSub:
    "Check recent earthquakes, storms and fires before planning a trip. Search a destination, read the agency reports and open the original sources—all without downloading an AI model.",
  heroCta: "Open the live map",
  heroSecondary: "Where the reports come from",
  liveTitle: "Explore recent hazard reports",
  loading: "Fetching official feeds",
  feedFailed: "unavailable",
  filterAll: "All",
  hazards: {
    earthquake: "Earthquakes",
    cyclone: "Storms",
    wildfire: "Wildfires",
    volcano: "Volcanoes",
    flood: "Floods",
    drought: "Drought",
    severe_weather: "US weather alerts",
    ice: "Sea ice",
    other: "Other",
  } as Record<string, string>,
  sourcesCount: (n: number) => `${n} source${n === 1 ? "" : "s"}`,
  pick: "Pick an incident on the map or in the list.",
  briefTemplate: "Quick summary",
  briefTemplateNote: "Built directly from the publishers' structured fields.",
  briefModel: "AI briefing",
  briefModelNote:
    "Drafted on your device, then checked for citations, numbers and alert level. Statements still need review.",
  writeBrief: "Write AI briefing",
  loadModel: "Download the AI (about 860 MB, once)",
  modelLoading: "Downloading the model to your browser",
  modelReady: (d: string) =>
    `Model ready on ${d === "webgpu" ? "your GPU" : "your CPU"}`,
  writing: "Writing",
  alert: "Alert level",
  alertMismatch: (e: string) => `Sources say ${e}`,
  verified: "Citation and number checks passed; review the statements",
  partly: "Some citation or number checks failed",
  rejected: "Claims that failed the check",
  sourcesTitle: "Sources for this incident",
  watch: "What to watch",
  howTitle: "A clearer view of the reports. A direct link to every source.",
  howSteps: [
    [
      "Collect",
      "Your browser fetches USGS, GDACS, NASA EONET and US National Weather Service feeds directly. Nothing passes through a server of ours.",
    ],
    [
      "Group",
      "Reports from different agencies about the same event are joined when the hazard, place and time agree. Earthquakes must also agree on magnitude.",
    ],
    [
      "Write",
      "The page builds a quick reading brief directly from the agencies’ structured fields. No model download or account is needed.",
    ],
    [
      "Check",
      "Each claim must cite a document and every number must appear in it. The alert level must equal the highest official level. Text that tries to instruct the model is removed first.",
    ],
  ],
  sourcesHeading: "Where the data comes from",
  limits:
    "Not an official warning service. Briefings repeat what the publishers say; they do not estimate casualties or forecast. Checks confirm citations and numbers, not truth.",
  trace: "Sources & checks",
  traceTitle: "Sources and summary checks",
  traceEmpty:
    "Feed requests appear here. Copy a source brief to record its fields and checks.",
  traceFeeds: "Feed requests",
  tracePrompt: "Source fields",
  traceRaw: "Summary output",
  traceChecks: "Checks",
  traceRemoved: "Removed as instruction-like text",
  close: "Close",
  footer:
    "Built by Srinivas Venigalla. Open source, runs in your browser, no tracking.",
  updated: (t: string) => `Updated ${t}`,
  refresh: "Refresh",
  lang: "日本語",
};
export type Strings = typeof EN;
const Ctx = createContext<{ lang: Lang; t: Strings; toggle: () => void }>({
  lang: "en",
  t: EN,
  toggle: () => {},
});
export function LangProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.lang = "en";
    localStorage.removeItem("lang");
  }, []);
  return (
    <Ctx.Provider value={{ lang: "en", t: EN, toggle: () => {} }}>
      {children}
    </Ctx.Provider>
  );
}
export const useT = () => useContext(Ctx);
