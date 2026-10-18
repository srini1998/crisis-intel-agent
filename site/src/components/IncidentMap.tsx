import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

// MapLibre 6 runs its tile parser in a module worker that Vite must serve as its own file.
maplibregl.setWorkerUrl(workerUrl);
import type { Incident } from "../lib/brief";
import { maxAlert } from "../lib/brief";

const COLORS: Record<string, string> = { red: "#d9534f", orange: "#e2853b", yellow: "#cdb34a", green: "#5fae7d", unknown: "#8aa0a8" };
const style = () => `https://tiles.openfreemap.org/styles/${matchMedia("(prefers-color-scheme: light)").matches ? "positron" : "dark"}`;

export function IncidentMap({ incidents, selected, onSelect }: { incidents: Incident[]; selected: string | null; onSelect: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const onReady = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({ container: box.current, style: style(), center: [20, 15], zoom: 1.2, attributionControl: { compact: true }, dragRotate: false });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("incidents", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "halo", type: "circle", source: "incidents", paint: { "circle-radius": ["+", ["get", "r"], 8], "circle-color": ["get", "c"], "circle-opacity": ["case", ["get", "sel"], 0.35, 0] } });
      m.addLayer({ id: "dots", type: "circle", source: "incidents", paint: { "circle-radius": ["get", "r"], "circle-color": ["get", "c"], "circle-opacity": 0.85, "circle-stroke-width": 1, "circle-stroke-color": "rgba(255,255,255,0.6)" } });
      m.on("click", "dots", (e: any) => {
        const id = e.features?.[0]?.properties?.id;
        if (id) onSelect(String(id));
      });
      m.on("mouseenter", "dots", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "dots", () => (m.getCanvas().style.cursor = ""));
      ready.current = true;
      onReady.current?.();
    });
    map.current = m;
    return () => m.remove();
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      const src = m.getSource("incidents") as maplibregl.GeoJSONSource | undefined;
      src?.setData({
        type: "FeatureCollection",
        features: incidents.filter((i) => i.lat != null && i.lon != null).map((i) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [i.lon!, i.lat!] },
          properties: { id: i.id, c: COLORS[maxAlert(i.members)] ?? COLORS.unknown, r: Math.max(4, Math.min(14, 4 + i.severity * 1.6)), sel: i.id === selected },
        })),
      });
    };
    if (ready.current) apply();
    else onReady.current = apply;
  }, [incidents, selected]);

  useEffect(() => {
    const i = incidents.find((x) => x.id === selected);
    if (map.current && i?.lat != null && i.lon != null) map.current.easeTo({ center: [i.lon, i.lat], zoom: Math.max(map.current.getZoom(), 3), duration: 900 });
  }, [selected]);

  return <div ref={box} className="h-[420px] w-full overflow-hidden rounded-3xl border border-line md:h-[520px]" role="region" aria-label="Incident map" />;
}
