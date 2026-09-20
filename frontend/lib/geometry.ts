export type Geometry = GeoJSON.Polygon | GeoJSON.MultiPolygon;

export function bboxForGeometry(geometry: Geometry): [number, number, number, number] {
  const rings: GeoJSON.Position[][] = geometry.type === "Polygon" ? geometry.coordinates : geometry.coordinates.flat();
  const points: GeoJSON.Position[] = rings.flat();
  const longitudes = points.map(([longitude]) => longitude);
  const latitudes = points.map(([, latitude]) => latitude);
  return [Math.min(...longitudes), Math.min(...latitudes), Math.max(...longitudes), Math.max(...latitudes)];
}

export function bboxString(geometry: Geometry): string {
  return bboxForGeometry(geometry).join(",");
}

export function areaSquareKilometers(geometry: Geometry): number {
  const ring = geometry.type === "Polygon" ? geometry.coordinates[0] : geometry.coordinates.flatMap((polygon) => polygon[0]);
  const latitude = ring.reduce((sum, [, value]) => sum + value, 0) / ring.length;
  const metersPerDegreeLat = 111_132;
  const metersPerDegreeLon = 111_320 * Math.cos((latitude * Math.PI) / 180);
  let signedArea = 0;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const [x1, y1] = ring[index];
    const [x2, y2] = ring[index + 1];
    signedArea += (x1 * metersPerDegreeLon) * (y2 * metersPerDegreeLat) - (x2 * metersPerDegreeLon) * (y1 * metersPerDegreeLat);
  }
  return Math.abs(signedArea / 2) / 1_000_000;
}
