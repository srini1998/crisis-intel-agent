import { GithubLogo } from "@phosphor-icons/react";
import type { FeedStatus } from "../lib/feeds";
import { useT } from "../i18n";

const SOURCES = [
  { id: "usgs", name: "USGS Earthquake Hazards Program", what: "M4.5+ earthquakes, past week", url: "https://earthquake.usgs.gov/earthquakes/feed/" },
  { id: "gdacs", name: "GDACS (UN / European Commission JRC)", what: "Multi-hazard alerts with green, orange, red levels", url: "https://www.gdacs.org/" },
  { id: "eonet", name: "NASA EONET", what: "Wildfires, storms, volcanoes, sea ice", url: "https://eonet.gsfc.nasa.gov/" },
  { id: "nws", name: "US National Weather Service", what: "Active severe and extreme weather alerts", url: "https://www.weather.gov/documentation/services-web-api" },
];

export function SourcesFooter({ status }: { status: FeedStatus[] }) {
  const { t, lang } = useT();
  return (
    <footer id="sources" className="scroll-mt-24 border-t border-line">
      <div className="mx-auto max-w-7xl px-4 py-24 md:px-8 md:py-32">
        <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t.sourcesHeading}</h2>
        <div className="mt-10 grid grid-cols-1 gap-x-12 gap-y-8 md:grid-cols-2">
          {SOURCES.map((s) => {
            const st = status.find((x) => x.source === s.id);
            return (
              <a key={s.id} href={s.url} target="_blank" rel="noopener noreferrer" className="group block">
                <p className="text-lg font-medium group-hover:text-signal">{s.name}</p>
                <p className="mt-1 text-muted">{s.what}{st ? (st.ok ? ` (${st.count})` : ` (${t.feedFailed})`) : ""}</p>
              </a>
            );
          })}
        </div>
        <p className="mt-14 max-w-[70ch] text-sm leading-relaxed text-muted">{t.limits}</p>
        <div className="mt-10 flex flex-wrap items-center justify-between gap-4 text-sm text-muted">
          <span>{t.footer}</span><a href="/THIRD_PARTY_NOTICES.txt">{lang === "ja" ? "モデル・ライセンス" : "Model & licenses"}</a>
          <a href="https://github.com/srini1998/crisis-intel-agent" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 hover:text-ink">
            <GithubLogo size={16} aria-hidden /> srini1998/crisis-intel-agent
          </a>
        </div>
      </div>
    </footer>
  );
}
