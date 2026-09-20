"use client";

import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";

import { imageryTileUrl } from "@/lib/api";

type Props = { beforeId: string; beforeYear: number; afterId: string; afterYear: number; onClose: () => void };

function createMap(node: HTMLDivElement, layerId: string): MapLibreMap {
  const map = new maplibregl.Map({
    container: node,
    center: [21.009, 52.229],
    zoom: 17,
    style: { version: 8, sources: { base: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256 }, aerial: { type: "raster", tiles: [imageryTileUrl(layerId)], tileSize: 256, attribution: "Orthophotomap: GUGiK / Geoportal.gov.pl" } }, layers: [{ id: "base", type: "raster", source: "base" }, { id: "aerial", type: "raster", source: "aerial" }] }
  });
  map.addControl(new maplibregl.NavigationControl(), "bottom-right");
  return map;
}

export function ComparisonPanel({ beforeId, beforeYear, afterId, afterYear, onClose }: Props) {
  const before = useRef<HTMLDivElement>(null);
  const after = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!before.current || !after.current) return;
    const beforeMap = createMap(before.current, beforeId);
    const afterMap = createMap(after.current, afterId);
    let syncing = false;
    const sync = (source: MapLibreMap, target: MapLibreMap) => {
      if (syncing) return;
      syncing = true;
      target.jumpTo({ center: source.getCenter(), zoom: source.getZoom(), bearing: source.getBearing(), pitch: source.getPitch() });
      syncing = false;
    };
    beforeMap.on("move", () => sync(beforeMap, afterMap));
    afterMap.on("move", () => sync(afterMap, beforeMap));
    return () => { beforeMap.remove(); afterMap.remove(); };
  }, [beforeId, afterId]);

  return <section className="absolute inset-4 z-30 overflow-hidden rounded-xl border border-slate-300 bg-white shadow-2xl" aria-label="Before and after imagery comparison">
    <header className="flex h-12 items-center justify-between border-b border-slate-200 px-4"><strong>Historical imagery comparison</strong><button className="button-secondary" onClick={onClose}>Close comparison</button></header>
    <div className="grid h-[calc(100%-3rem)] grid-cols-2 divide-x divide-slate-200"><div className="relative"><div ref={before} className="h-full" /><span className="comparison-label">Before: {beforeYear}</span></div><div className="relative"><div ref={after} className="h-full" /><span className="comparison-label">After: {afterYear}</span></div></div>
  </section>;
}
