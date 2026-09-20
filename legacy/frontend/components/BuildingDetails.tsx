"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type BuildingDetail } from "@/lib/api";
import { statusStyle } from "@/lib/status";

type Props = { detail: BuildingDetail; onClose: () => void; onCompare: () => void; onZoom: () => void };

const number = (value: number | null) => value === null ? "Not reported" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);

function exportBuilding(detail: BuildingDetail) {
  const blob = new Blob([JSON.stringify({ type: "Feature", id: detail.id, geometry: detail.geometry, properties: { status: detail.status, source_provider: detail.source_provider, source_object_type: detail.source_object_type, source_object_id: detail.source_object_id, osm_tags: detail.osm_tags, evidence: detail.evidence } }, null, 2)], { type: "application/geo+json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `roofer-building-${detail.id}.geojson`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function BuildingDetails({ detail, onClose, onCompare, onZoom }: Props) {
  const queryClient = useQueryClient();
  const review = useMutation({ mutationFn: ({ id, reviewed }: { id: string; reviewed: boolean }) => api.review(id, reviewed), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["building", detail.id] }) });
  const style = statusStyle[detail.status];
  return <aside className="details-panel" aria-label="Building evidence panel">
    <div className="flex items-start justify-between gap-3"><div><p className="eyebrow">Building evidence</p><h2 className="text-lg font-bold">{style.label}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close details">×</button></div>
    <div className="mt-3 rounded-lg border-l-4 p-3 text-sm" style={{ borderColor: style.color, backgroundColor: `${style.color}15` }}>{style.description}</div>
    <div className="details-actions"><button className="button-secondary" onClick={onZoom}>Zoom to building</button><button className="button-secondary" onClick={onCompare} disabled={!detail.evidence.some((item) => item.actual_removal_year)}>Compare imagery</button><button className="button-secondary" onClick={() => exportBuilding(detail)}>Export GeoJSON</button></div>
    <dl className="definition-list"><div><dt>OSM source</dt><dd>{detail.source_object_type}/{detail.source_object_id}</dd></div><div><dt>Provider</dt><dd>{detail.source_provider}</dd></div><div><dt>Selected imagery year</dt><dd>{detail.selected_imagery_year ?? "No verified layer selected"}</dd></div></dl>
    {detail.evidence.length === 0 ? <p className="empty-copy">No matching official registry record is stored for this building.</p> : detail.evidence.map((item) => <article key={item.match_id} className="evidence-card"><div className="flex items-center justify-between gap-2"><strong>{item.source_layer}</strong><span className="confidence">{Math.round(item.confidence * 100)}% match</span></div><dl className="definition-list compact"><div><dt>Registry feature</dt><dd>{item.source_feature_id}</dd></div><div><dt>Parcel</dt><dd>{item.parcel_number ?? "Not reported"}</dd></div><div><dt>Removal year</dt><dd>{item.actual_removal_year ?? "Not reported"}</dd></div><div><dt>Planned removal</dt><dd>{item.planned_removal_year ?? "Not reported"}</dd></div><div><dt>Inventoried / disposed</dt><dd>{number(item.inventory_amount)} / {number(item.disposed_amount)}</dd></div><div><dt>Urgency</dt><dd>{item.urgency ?? "Not reported"}</dd></div><div><dt>Evidence</dt><dd>{item.match_method}, {Math.round(item.overlap_ratio * 100)}% overlap</dd></div><div><dt>Last synchronization</dt><dd>{new Date(item.synchronized_at).toLocaleString()}</dd></div></dl><button className="button-secondary w-full" onClick={() => review.mutate({ id: item.match_id, reviewed: !item.manually_reviewed })}>{item.manually_reviewed ? "Mark unreviewed" : "Mark manually reviewed"}</button></article>)}
    <section className="warning-list"><h3>Limitations</h3>{detail.warnings.map((warning) => <p key={warning}>{warning}</p>)}</section>
  </aside>;
}
