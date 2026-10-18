import {
  ArrowDown,
  GlobeHemisphereWest,
  AirplaneTilt,
  Fire,
  Waveform,
  CloudLightning,
} from "@phosphor-icons/react";
import { useT } from "../i18n";
export function Hero() {
  const { t } = useT();
  return (
    <section
      id="top"
      className="mx-auto grid min-h-[85dvh] max-w-7xl grid-cols-1 items-center gap-12 px-4 pb-16 pt-32 md:px-8 lg:grid-cols-[1.25fr_1fr]"
    >
      <div className="max-w-3xl">
        <p className="mb-6 text-xs uppercase tracking-[.2em] text-signal">
          For the curious traveler
        </p>
        <h1 className="text-[clamp(2.6rem,5.8vw,5.3rem)] font-semibold leading-[1.02] tracking-tight">
          {t.heroTitle}
        </h1>
        <p className="mt-6 max-w-[49ch] text-lg leading-relaxed text-muted">
          {t.heroSub}
        </p>
        <a
          href="#live"
          className="mt-8 inline-flex items-center gap-3 rounded-full bg-signal px-6 py-3 font-medium text-white"
        >
          Explore a destination <ArrowDown aria-hidden size={18} />
        </a>
        <p className="mt-5 text-xs text-muted">
          USGS · GDACS · NASA EONET · US National Weather Service
        </p>
      </div>
      <div className="relative grid aspect-square place-items-center overflow-hidden rounded-3xl border border-line bg-panel">
        <GlobeHemisphereWest
          size={300}
          weight="thin"
          className="text-muted"
          aria-hidden
        />
        <AirplaneTilt
          size={35}
          className="absolute right-[15%] top-[20%] text-signal"
          aria-hidden
        />
        <div className="absolute bottom-6 left-6 right-6 grid gap-2">
          <div className="flex items-center gap-3 rounded-xl border border-line bg-paper/90 px-4 py-3 text-sm">
            <Waveform size={18} aria-hidden />
            Earthquakes <span className="ml-auto text-muted">USGS</span>
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-line bg-paper/90 px-4 py-3 text-sm">
            <CloudLightning size={18} aria-hidden />
            Storms & weather{" "}
            <span className="ml-auto text-muted">NWS / GDACS</span>
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-line bg-paper/90 px-4 py-3 text-sm">
            <Fire size={18} aria-hidden />
            Fires & natural events{" "}
            <span className="ml-auto text-muted">NASA</span>
          </div>
        </div>
      </div>
    </section>
  );
}
