import { describe, expect, it } from "vitest";

import { filterByStatus } from "@/lib/filters";
import { statusStyle } from "@/lib/status";

const feature = (status: "listed" | "cleaned" | "not_listed", beforeAfter = false) => ({ type: "Feature" as const, geometry: { type: "Polygon" as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties: { id: status, status, source_provider: "test", source_object_type: "way", source_object_id: status, osm_tags: {}, match_confidence: null, has_before_after_imagery: beforeAfter, manual_reviewed: false, registry_source_status: "available" } });

describe("registry presentation", () => {
  it("uses the required registry color categories", () => {
    expect(statusStyle.listed.color).toBe("#dc2626");
    expect(statusStyle.cleaned.color).toBe("#0f8b8d");
    expect(statusStyle.not_listed.label).toBe("Not listed");
    expect(statusStyle.not_listed.description).toContain("not evidence");
  });

  it("filters by status and before/after availability", () => {
    const rows = [feature("listed", true), feature("cleaned"), feature("not_listed", true)];
    expect(filterByStatus(rows, new Set(["listed", "not_listed"]))).toHaveLength(2);
    expect(filterByStatus(rows, new Set(["listed", "not_listed"]), true)).toHaveLength(2);
    expect(filterByStatus(rows, new Set(["cleaned"]), true)).toHaveLength(0);
  });
});
