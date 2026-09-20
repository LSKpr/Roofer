import type { BuildingFeature } from "@/lib/api";
import type { RegistryStatus } from "@/lib/status";

export function filterByStatus(features: BuildingFeature[], statuses: Set<RegistryStatus>, beforeAfterOnly = false): BuildingFeature[] {
  return features.filter((feature) => statuses.has(feature.properties.status) && (!beforeAfterOnly || feature.properties.has_before_after_imagery));
}
