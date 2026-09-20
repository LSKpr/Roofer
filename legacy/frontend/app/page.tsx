"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BuildingDetails } from "@/components/BuildingDetails";
import { ComparisonPanel } from "@/components/ComparisonPanel";
import { MapCanvas } from "@/components/MapCanvas";
import { api, exportUrl, type BuildingFeature } from "@/lib/api";
import { areaSquareKilometers, bboxString, type Geometry } from "@/lib/geometry";
import { statusStyle, visibleStatuses, type RegistryStatus } from "@/lib/status";

type DrawMode = "rectangle" | "polygon" | null;

const initialFilters = new Set<RegistryStatus>(visibleStatuses);
const warsawDemoArea: Geometry = { type: "Polygon", coordinates: [[[21.0077, 52.2282], [21.0113, 52.2282], [21.0113, 52.2308], [21.0077, 52.2308], [21.0077, 52.2282]]] };

export default function Home() {
  const [area, setArea] = useState<Geometry | null>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [aerial, setAerial] = useState(true);
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<{ label: string; center: [number, number] }[]>([]);
  const [focus, setFocus] = useState<[number, number] | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [selectedBuilding, setSelectedBuilding] = useState<BuildingFeature | null>(null);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [compareYear, setCompareYear] = useState<number | null>(null);
  const [visible, setVisible] = useState<Set<RegistryStatus>>(initialFilters);
  const [beforeAfterOnly, setBeforeAfterOnly] = useState(false);
  const [removalYearMin, setRemovalYearMin] = useState("");
  const [removalYearMax, setRemovalYearMax] = useState("");
  const [urgency, setUrgency] = useState("");
  const [minimumConfidence, setMinimumConfidence] = useState("");
  const [reviewed, setReviewed] = useState("all");
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [fitRequest, setFitRequest] = useState(0);

  const bbox = area ? bboxString(area) : null;
  const imagery = useQuery({ queryKey: ["imagery", bbox], queryFn: () => api.imagery(bbox!), enabled: Boolean(bbox) });
  const availableLayers = useMemo(() => [...(imagery.data ?? [])].sort((left, right) => left.acquisition_year - right.acquisition_year), [imagery.data]);

  useEffect(() => {
    if (!availableLayers.length) return;
    if (!selectedYear || !availableLayers.some((item) => item.acquisition_year === selectedYear)) setSelectedYear(availableLayers.at(-1)?.acquisition_year ?? null);
    if (!compareYear || !availableLayers.some((item) => item.acquisition_year === compareYear)) setCompareYear(availableLayers[0]?.acquisition_year ?? null);
  }, [availableLayers, compareYear, selectedYear]);

  const selectedLayer = availableLayers.find((item) => item.acquisition_year === selectedYear) ?? { id: "gugik-ortho-current", acquisition_year: 2025, attribution: "Orthophotomap: GUGiK / Geoportal.gov.pl" };
  const compareLayer = availableLayers.find((item) => item.acquisition_year === compareYear) ?? selectedLayer;

  const createJob = useMutation({ mutationFn: () => api.createJob(area!, [compareYear, selectedYear].filter((year): year is number => typeof year === "number")), onSuccess: (job) => { setJobId(job.id); setSelectedBuilding(null); } });
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId!), enabled: Boolean(jobId), refetchInterval: (query) => query.state.data?.status === "complete" || query.state.data?.status === "failed" ? false : 1200 });

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (visible.size !== visibleStatuses.length) params.set("status", [...visible].join(","));
    if (beforeAfterOnly) params.set("before_after_only", "true");
    if (removalYearMin) params.set("removal_year_min", removalYearMin);
    if (removalYearMax) params.set("removal_year_max", removalYearMax);
    if (urgency) params.set("urgency", urgency);
    if (minimumConfidence) params.set("minimum_confidence", minimumConfidence);
    if (reviewed !== "all") params.set("reviewed", reviewed);
    return params;
  }, [visible, beforeAfterOnly, removalYearMin, removalYearMax, urgency, minimumConfidence, reviewed]);
  const buildings = useQuery({ queryKey: ["job-buildings", jobId, query.toString()], queryFn: () => api.jobBuildings(jobId!, query), enabled: job.data?.status === "complete" });
  const detail = useQuery({ queryKey: ["building", selectedBuilding?.properties.id, jobId, selectedYear], queryFn: () => api.building(selectedBuilding!.properties.id, jobId ?? undefined, selectedYear ?? undefined), enabled: Boolean(selectedBuilding) });

  const searchMutation = useMutation({ mutationFn: () => api.geocode(search), onSuccess: setSearchResults });
  const setSelectedArea = useCallback((geometry: Geometry | null) => { setArea(geometry); setDrawMode(null); setJobId(null); setSelectedBuilding(null); }, []);
  const beginDrawing = useCallback((mode: Exclude<DrawMode, null>) => { setArea(null); setDrawMode(mode); setJobId(null); setSelectedBuilding(null); }, []);
  const selectBuilding = useCallback((feature: BuildingFeature) => { setSelectedBuilding(feature); setFitRequest((value) => value + 1); }, []);
  const toggleStatus = (status: RegistryStatus) => setVisible((current) => { const next = new Set(current); next.has(status) ? next.delete(status) : next.add(status); return next; });
  const canAnalyze = Boolean(area) && areaSquareKilometers(area!) <= 25 && !createJob.isPending;
  const selectedAreaSize = area ? areaSquareKilometers(area) : null;

  return <main className="map-shell">
    <MapCanvas features={buildings.data} aerial={aerial} imageryLayerId={selectedLayer.id} drawMode={drawMode} focus={focus} selectedArea={area} selectedBuildingId={selectedBuilding?.properties.id ?? null} selectedBuildingGeometry={detail.data?.geometry ?? selectedBuilding?.geometry ?? null} fitRequest={fitRequest} onAreaChange={setSelectedArea} onBuildingSelect={selectBuilding} />
    <section className="topbar" aria-label="Map controls">
      <div className="brand"><span className="brand-mark">R</span><div><h1>Roofer</h1><p>Poland asbestos evidence explorer</p></div></div>
      <form className="search" onSubmit={(event) => { event.preventDefault(); searchMutation.mutate(); }}><label className="sr-only" htmlFor="place-search">Search place or address</label><input id="place-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search a place or address in Poland" minLength={3} /><button className="button-primary" type="submit" disabled={searchMutation.isPending}>Search</button></form>
      <div className="top-actions"><button className="button-secondary" onClick={() => setAerial((value) => !value)}>{aerial ? "Standard map" : "Aerial imagery"}</button><button className="button-disabled" disabled title="A roof-classification model is not configured.">Run ML analysis</button></div>
    </section>
    {searchResults.length > 0 && <section className="search-results">{searchResults.map((result) => <button key={result.label} onClick={() => { setFocus(result.center); setSearchResults([]); }}>{result.label}</button>)}</section>}
    <aside className="left-panel" aria-label="Analysis controls">
      <p className="eyebrow">Area analysis</p><h2>Draw, verify, analyze</h2><p className="panel-copy">Registry data is official but not laboratory confirmation. An unlisted building is never called clean.</p>
      <div className="button-row"><button className={drawMode === "rectangle" ? "button-primary" : "button-secondary"} onClick={() => beginDrawing("rectangle")}>Draw rectangle</button><button className={drawMode === "polygon" ? "button-primary" : "button-secondary"} onClick={() => beginDrawing("polygon")}>Draw polygon</button><button className="button-secondary" onClick={() => { setSelectedArea(warsawDemoArea); setFocus([21.0095, 52.2295]); }}>Load Warsaw demo area</button></div>
      {drawMode && <p className="draw-help">{drawMode === "rectangle" ? "Press on the map, drag to the opposite corner, then release." : "Click each boundary vertex, then double-click the final vertex to finish."}</p>}
      {area && <div className="selection-summary"><strong>Selected area</strong><span>{selectedAreaSize?.toFixed(2)} km² of 25 km² maximum</span><button className="text-button" onClick={() => setSelectedArea(null)}>Clear selection</button></div>}
      {area && <section className="year-control"><div className="flex items-center justify-between"><h3>Verified imagery</h3><strong>{selectedLayer.acquisition_year}</strong></div>{imagery.isLoading ? <p>Checking official coverage…</p> : availableLayers.length ? <><input aria-label="Imagery year" type="range" min={0} max={availableLayers.length - 1} value={Math.max(0, availableLayers.findIndex((layer) => layer.acquisition_year === selectedYear))} onChange={(event) => setSelectedYear(availableLayers[Number(event.target.value)].acquisition_year)} /><div className="year-labels"><span>{availableLayers[0].acquisition_year}</span><span>{availableLayers.at(-1)?.acquisition_year}</span></div><p>{selectedLayer.attribution}</p><label>Comparison year<select value={compareYear ?? ""} onChange={(event) => setCompareYear(Number(event.target.value))}>{availableLayers.map((layer) => <option key={layer.id} value={layer.acquisition_year}>{layer.acquisition_year}</option>)}</select></label></> : <p>No verified historical year is available for this area.</p>}</section>}
      <button className="button-primary analyze-button" disabled={!canAnalyze} onClick={() => createJob.mutate()}>{createJob.isPending ? "Creating analysis…" : "Analyze area"}</button>
      {area && selectedAreaSize && selectedAreaSize > 25 && <p className="error-copy">The selected area exceeds the configured 25 km² limit.</p>}
      {createJob.isError && <p className="error-copy">{createJob.error.message}</p>}
      {job.data && <section className="progress"><div className="flex justify-between"><strong>{job.data.stage}</strong><span>{job.data.progress}%</span></div><div className="progress-track"><div style={{ width: `${job.data.progress}%` }} /></div>{job.data.errors.map((error) => <p className="source-warning" key={`${error.source}-${error.message}`}>{error.message}</p>)}</section>}
      {job.data?.status === "complete" && buildings.data && <section className="result-list"><p className="eyebrow">Analyzed buildings</p>{buildings.data.features.map((feature) => <button key={feature.properties.id} className={selectedBuilding?.properties.id === feature.properties.id ? "selected" : ""} onClick={() => selectBuilding(feature)}><span className="legend-swatch" style={{ background: statusStyle[feature.properties.status].color }} /><span>Building {feature.properties.source_object_id}</span><small>{statusStyle[feature.properties.status].label}</small></button>)}</section>}
    </aside>
    <aside className="right-panel" aria-label="Legend and filters"><section><p className="eyebrow">Legend</p><h2>Registry status</h2>{visibleStatuses.map((status) => <label key={status} className="legend-row"><input type="checkbox" checked={visible.has(status)} onChange={() => toggleStatus(status)} /><span className="legend-swatch" style={{ background: statusStyle[status].color }} /><span>{statusStyle[status].label}</span></label>)}<p className="legend-note">Orange is reserved for a future ML model and is intentionally not shown.</p></section><section className="filters"><p className="eyebrow">Filters</p><label>Removal year from<input type="number" value={removalYearMin} onChange={(event) => setRemovalYearMin(event.target.value)} placeholder="e.g. 2020" /></label><label>Removal year to<input type="number" value={removalYearMax} onChange={(event) => setRemovalYearMax(event.target.value)} placeholder="e.g. 2025" /></label><label>Urgency<input value={urgency} onChange={(event) => setUrgency(event.target.value)} placeholder="Reported urgency" /></label><label>Minimum confidence<input type="number" min="0" max="1" step="0.05" value={minimumConfidence} onChange={(event) => setMinimumConfidence(event.target.value)} placeholder="0.70" /></label><label>Review state<select value={reviewed} onChange={(event) => setReviewed(event.target.value)}><option value="all">All</option><option value="true">Manually reviewed</option><option value="false">Unreviewed</option></select></label><label className="legend-row"><input type="checkbox" checked={beforeAfterOnly} onChange={(event) => setBeforeAfterOnly(event.target.checked)} />Has before/after imagery</label></section>{job.data?.status === "complete" && <section className="stats"><p className="eyebrow">Selected area</p><h2>Statistics</h2>{Object.entries(job.data.counts).map(([name, value]) => <div key={name}><span>{name.replaceAll("_", " ")}</span><strong>{value}</strong></div>)}<div className="export-row"><a className="button-secondary" href={exportUrl(job.data.id, "geojson", [...visible])}>GeoJSON</a><a className="button-secondary" href={exportUrl(job.data.id, "csv", [...visible])}>CSV</a></div></section>}</aside>
    {detail.data && <BuildingDetails detail={detail.data} onClose={() => setSelectedBuilding(null)} onZoom={() => setFitRequest((value) => value + 1)} onCompare={() => setComparisonOpen(true)} />}
    {comparisonOpen && <ComparisonPanel beforeId={compareLayer.id} beforeYear={compareLayer.acquisition_year} afterId={selectedLayer.id} afterYear={selectedLayer.acquisition_year} onClose={() => setComparisonOpen(false)} />}
    <footer className="map-attribution">{aerial ? selectedLayer.attribution : "© OpenStreetMap contributors"} · Use registry data as evidence, not a safety determination.</footer>
  </main>;
}
