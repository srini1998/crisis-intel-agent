import { useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { useT } from "../i18n";

gsap.registerPlugin(ScrollTrigger);

export function HowItWorks() {
  const { t } = useT();
  const root = useRef<HTMLElement>(null);
  // Motivation: the four steps are a sequence, so they reveal in order while the claim stays in view.
  useGSAP(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const mm = gsap.matchMedia();
    mm.add("(min-width: 1024px)", () => {
      ScrollTrigger.create({ trigger: root.current, start: "top top", end: "bottom bottom", pin: "[data-pin]", pinSpacing: false });
    });
    gsap.utils.toArray<HTMLElement>("[data-step]").forEach((el) => {
      gsap.fromTo(el, { opacity: 0.15, y: 30 }, { opacity: 1, y: 0, ease: "none", scrollTrigger: { trigger: el, start: "top 85%", end: "top 45%", scrub: true } });
    });
    return () => mm.revert();
  }, { scope: root });

  return (
    <section id="how" ref={root} className="relative mx-auto grid max-w-7xl scroll-mt-24 grid-cols-1 gap-12 px-4 py-24 md:px-8 md:py-40 lg:grid-cols-[1fr_1.1fr]">
      <div data-pin className="lg:h-[100dvh] lg:pt-32">
        <h2 className="max-w-xl text-3xl font-semibold leading-tight tracking-tight md:text-5xl">{t.howTitle}</h2>
      </div>
      <ol className="space-y-24 lg:pt-32">
        {t.howSteps.map(([title, body]) => (
          <li key={title} data-step className="border-l-2 border-signal pl-6">
            <h3 className="text-2xl font-semibold">{title}</h3>
            <p className="mt-3 max-w-[60ch] text-lg leading-relaxed text-muted">{body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
