export type RegistryStatus = "listed" | "cleaned" | "not_listed" | "ambiguous" | "unknown";

export const statusStyle: Record<RegistryStatus, { label: string; color: string; description: string }> = {
  listed: { label: "Listed in registry", color: "#dc2626", description: "Official GeoAzbest registry record indicates asbestos-containing material is listed." },
  cleaned: { label: "Listed as cleaned", color: "#0f8b8d", description: "Official registry contains a cleaned/removal record; material scope may not be the full roof." },
  not_listed: { label: "Not listed", color: "#6b7280", description: "An OSM building is not matched to the registry. This is not evidence of an asbestos-free roof." },
  ambiguous: { label: "Ambiguous", color: "#7c3aed", description: "Conflicting or multiple registry records need review." },
  unknown: { label: "Unknown", color: "#9ca3af", description: "The official source was unavailable or records could not establish a status." }
};

export const visibleStatuses: RegistryStatus[] = ["listed", "cleaned", "not_listed", "ambiguous", "unknown"];
