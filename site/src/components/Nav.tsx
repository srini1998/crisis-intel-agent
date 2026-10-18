import { Pulse } from "@phosphor-icons/react";
import { useT } from "../i18n";

export function Nav() {
  const { t } = useT();
  return (
    <header className="fixed inset-x-0 top-4 z-30 flex justify-center px-4">
      <nav className="flex w-full max-w-5xl items-center justify-between gap-4 rounded-full border border-line bg-panel/80 px-5 py-2.5 backdrop-blur-md">
        <a
          href="#top"
          className="flex items-center gap-2 font-semibold tracking-tight"
        >
          <Pulse size={20} weight="bold" className="text-signal" aria-hidden />
          Fieldbrief
        </a>
        <div className="hidden items-center gap-6 text-sm text-muted md:flex">
          <a href="#live" className="hover:text-ink">
            {t.navLive}
          </a>
          <a href="#how" className="hover:text-ink">
            {t.navHow}
          </a>
          <a href="#sources" className="hover:text-ink">
            {t.navSources}
          </a>
        </div>
        <a
          href="https://my-portfolio-three-omega-46.vercel.app"
          className="text-sm text-muted"
        >
          Portfolio ↗
        </a>
      </nav>
    </header>
  );
}
