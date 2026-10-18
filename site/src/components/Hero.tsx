import { lazy, Suspense, useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ArrowDown } from "@phosphor-icons/react";
import { useT } from "../i18n";

// ThreeUI Community (MIT): animated topographic contour field, loaded after first paint.
const TopoField = lazy(() => import("@designcodeio/threeui/components/TopoField").then((m) => ({ default: m.TopoField })));

export function Hero() {
  const { t } = useT();
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    gsap.from("[data-hero-line]", { y: 28, opacity: 0, duration: 0.9, stagger: 0.08, ease: "power3.out" });
    gsap.from("[data-hero-visual]", { scale: 0.94, opacity: 0, duration: 1.2, ease: "power2.out", delay: 0.15 });
  }, { scope: root });

  return (
    <section id="top" ref={root} className="mx-auto grid min-h-[100dvh] max-w-7xl grid-cols-1 items-center gap-12 px-4 pb-16 pt-28 md:px-8 lg:grid-cols-[1.25fr_1fr]">
      <div className="max-w-3xl">
        <h1 data-hero-line className="text-[clamp(2.4rem,5vw,4.6rem)] font-semibold leading-[1.04] tracking-tight">{t.heroTitle}</h1>
        <p data-hero-line className="mt-6 max-w-[52ch] text-lg leading-relaxed text-muted">{t.heroSub}</p>
        <div data-hero-line className="mt-8 flex flex-wrap gap-3">
          <a href="#live" className="inline-flex items-center gap-2 rounded-full bg-signal px-6 py-3 font-medium text-white transition-transform hover:-translate-y-0.5 active:scale-[0.98]">
            {t.heroCta} <ArrowDown size={16} weight="bold" aria-hidden />
          </a>
          <a href="#how" className="inline-flex items-center rounded-full border border-line px-6 py-3 font-medium hover:border-signal">{t.heroSecondary}</a>
        </div>
      </div>
      <div data-hero-visual className="relative aspect-[16/10] w-full overflow-hidden rounded-[28px] border border-line bg-panel lg:aspect-[5/6]">
        <Suspense fallback={<div className="h-full w-full animate-pulse bg-panel" />}>
          <TopoField className="absolute inset-0 h-full w-full" mode="dark" hue={22} saturation={1.2} brightness={1.8} speed={0.45} strokeWidth={1.4} />
        </Suspense>
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-paper/70 via-transparent to-transparent" />
      </div>
    </section>
  );
}
