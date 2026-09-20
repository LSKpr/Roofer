"use client";

import * as maplibregl from "maplibre-gl";
import type { LngLatLike, Map as MapLibreMap } from "maplibre-gl";
import { useCallback, useEffect, useRef } from "react";

import { imageryTileUrl, type BuildingFeature, type FeatureCollection } from "@/lib/api";
import { bboxForGeometry, type Geometry } from "@/lib/geometry";
import { statusStyle } from "@/lib/status";

type DrawMode = "rectangle" | "polygon" | null;

type Props = {
  features: FeatureCollection | undefined;
  aerial: boolean;
  imageryLayerId: string;
  drawMode: DrawMode;
  focus?: [number, number] | null;
  selectedArea: Geometry | null;
  selectedBuildingId: string | null;
  selectedBuildingGeometry: Geometry | null;
  fitRequest: number;
  onAreaChange: (geometry: Geometry | null) => void;
  onBuildingSelect: (feature: BuildingFeature) => void;
};

const emptyCollection: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function geometryCollection(...geometries: GeoJSON.Geometry[]): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: geometries.map((geometry) => ({ type: "Feature", properties: {}, geometry })) };
}

function ringsOf(geometry: Geometry): GeoJSON.Position[][] {
  return geometry.type === "Polygon" ? geometry.coordinates : geometry.coordinates.flat();
}

function polygonPath(map: MapLibreMap, geometry: Geometry | null): string {
  if (!geometry) return "";
  return ringsOf(geometry)
    .map((ring) => ring.map((point, index) => {
      const projected = map.project([point[0], point[1]]);
      return `${index === 0 ? "M" : "L"}${projected.x.toFixed(1)} ${projected.y.toFixed(1)}`;
    }).join(" ") + " Z")
    .join(" ");
}

function linePath(map: MapLibreMap, points: [number, number][]): string {
  if (points.length < 2) return "";
  return points.map((point, index) => {
    const projected = map.project(point);
    return `${index === 0 ? "M" : "L"}${projected.x.toFixed(1)} ${projected.y.toFixed(1)}`;
  }).join(" ");
}

function vertexPath(map: MapLibreMap, points: [number, number][], radius = 6): string {
  return points.map((point) => {
    const projected = map.project(point);
    return `M${(projected.x - radius).toFixed(1)} ${projected.y.toFixed(1)} a${radius} ${radius} 0 1 0 ${radius * 2} 0 a${radius} ${radius} 0 1 0 ${-radius * 2} 0`;
  }).join(" ");
}

function screenRectanglePath(map: MapLibreMap, start: [number, number], end: [number, number]): string {
  const from = map.project(start);
  const to = map.project(end);
  return `M${from.x.toFixed(1)} ${from.y.toFixed(1)} L${to.x.toFixed(1)} ${from.y.toFixed(1)} L${to.x.toFixed(1)} ${to.y.toFixed(1)} L${from.x.toFixed(1)} ${to.y.toFixed(1)} Z`;
}

const mapStyle = {
  version: 8,
  sources: {
    standard: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap contributors"
    }
  },
  layers: [{ id: "standard", type: "raster", source: "standard" }]
} as maplibregl.StyleSpecification;

export function MapCanvas({ features, aerial, imageryLayerId, drawMode, focus, selectedArea, selectedBuildingId, selectedBuildingGeometry, fitRequest, onAreaChange, onBuildingSelect }: Props) {
  const mapNode = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const selectionPathRef = useRef<SVGPathElement>(null);
  const draftLineRef = useRef<SVGPathElement>(null);
  const draftVertexRef = useRef<SVGPathElement>(null);
  const buildingPathRef = useRef<SVGPathElement>(null);
  const drawModeRef = useRef<DrawMode>(drawMode);
  const polygonPoints = useRef<[number, number][]>([]);
  const rectangleStart = useRef<[number, number] | null>(null);
  const rectangleCurrent = useRef<[number, number] | null>(null);
  const areaChangeRef = useRef(onAreaChange);
  const buildingSelectRef = useRef(onBuildingSelect);
  const aerialRef = useRef(aerial);
  const imageryLayerRef = useRef(imageryLayerId);
  const featuresRef = useRef(features);
  const selectedAreaRef = useRef(selectedArea);
  const selectedBuildingIdRef = useRef(selectedBuildingId);
  const selectedBuildingGeometryRef = useRef(selectedBuildingGeometry);

  featuresRef.current = features;
  selectedAreaRef.current = selectedArea;
  selectedBuildingIdRef.current = selectedBuildingId;
  selectedBuildingGeometryRef.current = selectedBuildingGeometry;

  const drawOverlay = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const committed = selectedAreaRef.current;
    const drafting = rectangleStart.current && rectangleCurrent.current
      ? screenRectanglePath(map, rectangleStart.current, rectangleCurrent.current)
      : polygonPoints.current.length > 1 ? linePath(map, polygonPoints.current) : "";
    if (selectionPathRef.current) selectionPathRef.current.setAttribute("d", rectangleStart.current ? drafting : polygonPath(map, committed));
    if (draftLineRef.current) draftLineRef.current.setAttribute("d", rectangleStart.current ? "" : drafting);
    if (draftVertexRef.current) draftVertexRef.current.setAttribute("d", vertexPath(map, polygonPoints.current));
    if (buildingPathRef.current) buildingPathRef.current.setAttribute("d", polygonPath(map, selectedBuildingGeometryRef.current));
  }, []);

  useEffect(() => {
    areaChangeRef.current = onAreaChange;
    buildingSelectRef.current = onBuildingSelect;
    aerialRef.current = aerial;
    imageryLayerRef.current = imageryLayerId;
  }, [aerial, imageryLayerId, onAreaChange, onBuildingSelect]);

  drawModeRef.current = drawMode;

  useEffect(() => {
    polygonPoints.current = [];
    rectangleStart.current = null;
    rectangleCurrent.current = null;
    const map = mapRef.current;
    if (!map) return;
    map.getCanvas().style.cursor = drawMode ? "crosshair" : "";
    if (drawMode === "polygon") map.doubleClickZoom.disable();
    else map.doubleClickZoom.enable();
    if (drawMode === "rectangle") map.dragPan.disable();
    else map.dragPan.enable();
    const source = map.getSource("selection") as maplibregl.GeoJSONSource | undefined;
    if (drawMode && source) source.setData(emptyCollection);
    drawOverlay();
  }, [drawMode, drawOverlay]);

  useEffect(() => {
    if (!mapNode.current || mapRef.current) return;
    const map = new maplibregl.Map({ container: mapNode.current, style: mapStyle, center: [19.2, 52.05] as LngLatLike, zoom: 6, minZoom: 5, maxZoom: 21 });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.on("style.load", () => {
      map.addSource("aerial", { type: "raster", tiles: [imageryTileUrl(imageryLayerRef.current)], tileSize: 256, attribution: "Orthophotomap: GUGiK / Geoportal.gov.pl" });
      map.addLayer({ id: "aerial", type: "raster", source: "aerial", layout: { visibility: aerialRef.current ? "visible" : "none" } });
      map.addSource("buildings", { type: "geojson", data: featuresRef.current ?? emptyCollection });
      map.addLayer({ id: "building-fill", type: "fill", source: "buildings", paint: { "fill-color": ["match", ["get", "status"], "listed", statusStyle.listed.color, "cleaned", statusStyle.cleaned.color, "ambiguous", statusStyle.ambiguous.color, "unknown", statusStyle.unknown.color, statusStyle.not_listed.color], "fill-opacity": 0.62 } });
      map.addLayer({ id: "building-line", type: "line", source: "buildings", paint: { "line-color": ["match", ["get", "status"], "listed", statusStyle.listed.color, "cleaned", statusStyle.cleaned.color, "ambiguous", statusStyle.ambiguous.color, "unknown", statusStyle.unknown.color, statusStyle.not_listed.color], "line-width": ["case", ["==", ["get", "status"], "not_listed"], 3, 2] } });
      const selectedFilter = ["==", ["get", "id"], selectedBuildingIdRef.current ?? ""] as maplibregl.FilterSpecification;
      map.addLayer({ id: "building-selected-fill", type: "fill", source: "buildings", filter: selectedFilter, paint: { "fill-color": "#facc15", "fill-opacity": 0.42 } });
      map.addLayer({ id: "building-selected-line", type: "line", source: "buildings", filter: selectedFilter, paint: { "line-color": "#fde047", "line-width": 6 } });
      map.addSource("selection", { type: "geojson", data: selectedAreaRef.current ? geometryCollection(selectedAreaRef.current) : emptyCollection });
      map.addLayer({ id: "selection-fill", type: "fill", source: "selection", paint: { "fill-color": "#2563eb", "fill-opacity": 0.08 } });
      map.addLayer({ id: "selection-line", type: "line", source: "selection", paint: { "line-color": "#1d4ed8", "line-width": 4 } });
      map.addLayer({ id: "selection-points", type: "circle", source: "selection", paint: { "circle-color": "#2563eb", "circle-radius": 5, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
      if (drawModeRef.current) map.getCanvas().style.cursor = "crosshair";
      if (drawModeRef.current === "polygon") map.doubleClickZoom.disable();
      if (drawModeRef.current === "rectangle") map.dragPan.disable();
      drawOverlay();
      map.on("render", drawOverlay);
      map.on("click", "building-fill", (event) => {
        const feature = event.features?.[0] as BuildingFeature | undefined;
        if (!drawModeRef.current && feature) buildingSelectRef.current(feature);
      });
      map.on("mouseenter", "building-fill", () => { map.getCanvas().style.cursor = drawModeRef.current ? "crosshair" : "pointer"; });
      map.on("mouseleave", "building-fill", () => { map.getCanvas().style.cursor = drawModeRef.current ? "crosshair" : ""; });
      map.on("mousedown", (event) => {
        if (drawModeRef.current !== "rectangle" || event.originalEvent.button !== 0) return;
        event.preventDefault();
        rectangleStart.current = [event.lngLat.lng, event.lngLat.lat];
        rectangleCurrent.current = [event.lngLat.lng, event.lngLat.lat];
        const source = map.getSource("selection") as maplibregl.GeoJSONSource;
        source.setData(geometryCollection({ type: "Point", coordinates: rectangleStart.current }));
        drawOverlay();
      });
      map.on("mouseup", (event) => {
        if (drawModeRef.current !== "rectangle" || !rectangleStart.current) return;
        const start = rectangleStart.current;
        const end: [number, number] = [event.lngLat.lng, event.lngLat.lat];
        rectangleStart.current = null;
        rectangleCurrent.current = null;
        if (Math.abs(start[0] - end[0]) < 0.000001 || Math.abs(start[1] - end[1]) < 0.000001) {
          drawOverlay();
          return;
        }
        const geometry: GeoJSON.Polygon = {
          type: "Polygon",
          coordinates: [[
            [start[0], start[1]],
            [end[0], start[1]],
            [end[0], end[1]],
            [start[0], end[1]],
            [start[0], start[1]],
          ]],
        };
        areaChangeRef.current(geometry);
      });
      map.on("click", (event) => {
        const mode = drawModeRef.current;
        if (!mode) return;
        const coordinate: [number, number] = [event.lngLat.lng, event.lngLat.lat];
        const source = map.getSource("selection") as maplibregl.GeoJSONSource;
        if (mode === "rectangle") return;
        polygonPoints.current = [...polygonPoints.current, coordinate];
        const draft: GeoJSON.Geometry[] = [{ type: "MultiPoint", coordinates: polygonPoints.current }];
        if (polygonPoints.current.length >= 2) draft.push({ type: "LineString", coordinates: polygonPoints.current });
        source.setData(geometryCollection(...draft));
        drawOverlay();
      });
      map.on("dblclick", (event) => {
        if (drawModeRef.current !== "polygon") return;
        event.preventDefault();
        const points = polygonPoints.current.filter((point, index, all) => index === 0 || point[0] !== all[index - 1][0] || point[1] !== all[index - 1][1]);
        if (points.length < 3) return;
        areaChangeRef.current({ type: "Polygon", coordinates: [[...points, points[0]]] });
        polygonPoints.current = [];
      });
      map.on("mousemove", (event) => {
        const source = map.getSource("selection") as maplibregl.GeoJSONSource;
        const coordinate: [number, number] = [event.lngLat.lng, event.lngLat.lat];
        if (drawModeRef.current === "rectangle" && rectangleStart.current) {
          rectangleCurrent.current = coordinate;
          const [startLon, startLat] = rectangleStart.current;
          const geometry: GeoJSON.Polygon = { type: "Polygon", coordinates: [[[startLon, startLat], [coordinate[0], startLat], [coordinate[0], coordinate[1]], [startLon, coordinate[1]], [startLon, startLat]]] };
          source.setData(geometryCollection(geometry, { type: "MultiPoint", coordinates: [rectangleStart.current, coordinate] }));
          drawOverlay();
        } else if (drawModeRef.current === "polygon" && polygonPoints.current.length) {
          source.setData(geometryCollection({ type: "MultiPoint", coordinates: polygonPoints.current }, { type: "LineString", coordinates: [...polygonPoints.current, coordinate] }));
          if (draftLineRef.current) draftLineRef.current.setAttribute("d", linePath(map, [...polygonPoints.current, coordinate]));
        }
      });
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, [drawOverlay]);

  useEffect(() => {
    const map = mapRef.current;
    const source = map?.getSource("buildings") as maplibregl.GeoJSONSource | undefined;
    if (source && features) source.setData(features);
  }, [features]);

  useEffect(() => {
    const map = mapRef.current;
    const source = map?.getSource("selection") as maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(selectedArea ? geometryCollection(selectedArea) : emptyCollection);
    drawOverlay();
  }, [selectedArea, drawOverlay]);

  useEffect(() => {
    const map = mapRef.current;
    drawOverlay();
    if (!map?.getLayer("building-selected-fill")) return;
    const filter = ["==", ["get", "id"], selectedBuildingId ?? ""] as maplibregl.FilterSpecification;
    map.setFilter("building-selected-fill", filter);
    map.setFilter("building-selected-line", filter);
  }, [selectedBuildingId, selectedBuildingGeometry, drawOverlay]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedBuildingGeometry) return;
    const [minLon, minLat, maxLon, maxLat] = bboxForGeometry(selectedBuildingGeometry);
    map.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 180, maxZoom: 19, duration: 700 });
  }, [selectedBuildingGeometry, fitRequest]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("aerial")) return;
    map.setLayoutProperty("aerial", "visibility", aerial ? "visible" : "none");
  }, [aerial]);

  useEffect(() => {
    const map = mapRef.current;
    const source = map?.getSource("aerial") as maplibregl.RasterTileSource | undefined;
    if (source) source.setTiles([imageryTileUrl(imageryLayerId)]);
  }, [imageryLayerId]);

  useEffect(() => {
    if (focus) mapRef.current?.flyTo({ center: focus, zoom: 16, essential: true });
  }, [focus]);

  return <div className="map-stage relative h-full w-full"><div ref={mapNode} className="absolute inset-0" aria-label="Interactive map of Polish building and registry evidence" /><svg className="map-overlay" aria-hidden="true"><path ref={selectionPathRef} className="overlay-selection" d="" /><path ref={draftLineRef} className="overlay-draft-line" d="" /><path ref={draftVertexRef} className="overlay-draft-vertex" d="" /><path ref={buildingPathRef} className="overlay-building" d="" /></svg>{drawMode && <div className="map-draw-banner" role="status"><strong>{drawMode === "rectangle" ? "Draw an analysis rectangle" : "Draw an analysis polygon"}</strong><span>{drawMode === "rectangle" ? "Press on the map, drag to the opposite corner, then release." : "Click boundary points and double-click the final point."}</span><button type="button" onClick={() => areaChangeRef.current(null)}>Cancel</button></div>}</div>;
}
