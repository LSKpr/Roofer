import type { Geometry } from "@/lib/geometry";
import type { RegistryStatus } from "@/lib/status";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export type Evidence = {
  match_id: string;
  source_feature_id: string;
  source_layer: string;
  status: string;
  location_id: string | null;
  parcel_number: string | null;
  teryt: string | null;
  urgency: string | null;
  planned_removal_year: number | null;
  actual_removal_year: number | null;
  inventory_amount: number | null;
  disposed_amount: number | null;
  synchronized_at: string;
  match_method: string;
  intersection_area_m2: number;
  overlap_ratio: number;
  confidence: number;
  ambiguous: boolean;
  manually_reviewed: boolean;
};

export type BuildingProperties = {
  id: string;
  status: RegistryStatus;
  source_provider: string;
  source_object_type: string;
  source_object_id: string;
  osm_tags: Record<string, unknown>;
  match_confidence: number | null;
  has_before_after_imagery: boolean;
  manual_reviewed: boolean;
  registry_source_status: string;
};

export type BuildingFeature = GeoJSON.Feature<Geometry, BuildingProperties>;
export type FeatureCollection = GeoJSON.FeatureCollection<Geometry, BuildingProperties>;

export type Job = {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  progress: number;
  stage: string;
  counts: Record<string, number>;
  errors: { source: string; message: string }[];
  registry_source_status: string;
  started_at: string | null;
  completed_at: string | null;
};

export type BuildingDetail = {
  id: string;
  status: RegistryStatus;
  geometry: Geometry;
  source_provider: string;
  source_object_type: string;
  source_object_id: string;
  osm_tags: Record<string, unknown>;
  evidence: Evidence[];
  warnings: string[];
  selected_imagery_year: number | null;
  data_source_timestamps: Record<string, string | null>;
};

export type ImageryLayer = {
  id: string;
  provider: string;
  layer_id: string;
  acquisition_year: number;
  acquisition_date_range: string | null;
  resolution_m: number | null;
  coverage: Geometry | null;
  attribution: string;
  license_metadata: string;
  service_configuration: Record<string, unknown>;
  verified_for_area: boolean;
};

export type GeocodeResult = { label: string; center: [number, number]; bbox: [number, number, number, number] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  createJob: (geometry: Geometry, requestedYears: number[]) => request<Job>("/analysis-jobs", { method: "POST", body: JSON.stringify({ geometry, requested_years: requestedYears }) }),
  job: (id: string) => request<Job>(`/analysis-jobs/${id}`),
  jobBuildings: (id: string, filters: URLSearchParams) => request<FeatureCollection>(`/analysis-jobs/${id}/buildings?${filters.toString()}`),
  building: (id: string, jobId?: string, selectedYear?: number) => request<BuildingDetail>(`/buildings/${id}?${new URLSearchParams({ ...(jobId ? { job_id: jobId } : {}), ...(selectedYear ? { selected_imagery_year: String(selectedYear) } : {}) })}`),
  imagery: (bbox: string) => request<ImageryLayer[]>(`/imagery/available?bbox=${encodeURIComponent(bbox)}`),
  geocode: (query: string) => request<GeocodeResult[]>(`/geocode?q=${encodeURIComponent(query)}`),
  review: (id: string, reviewed: boolean) => request<{ id: string; manual_reviewed: boolean }>(`/matches/${id}/review`, { method: "PUT", body: JSON.stringify({ reviewed }) })
};

export function exportUrl(jobId: string, format: "geojson" | "csv", statuses: RegistryStatus[]): string {
  const query = new URLSearchParams({ format, ...(statuses.length ? { status: statuses.join(",") } : {}) });
  return `${apiBase}/analysis-jobs/${jobId}/export?${query}`;
}

export function imageryTileUrl(id: string): string {
  return `${apiBase}/imagery/tiles/${id}/{z}/{x}/{y}.jpg?v=standard-resolution-v1`;
}
