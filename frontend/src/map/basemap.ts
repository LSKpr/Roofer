import type { StyleSpecification } from 'maplibre-gl'

/** Kafle OSM sa dobre na development. Przed publicznym demem potrzebujemy wlasnego zrodla. */
export const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
export const OSM_ATTRIBUTION = '© OpenStreetMap contributors'

export const basemapStyle: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: [OSM_TILES],
      tileSize: 256,
      maxzoom: 19,
      attribution: OSM_ATTRIBUTION,
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
}

/**
 * Okolice Zwolenia, nie Warszawa. W stolicy zgloszonych jest 0,1% budynkow, wiec mapa na starcie
 * wygladalaby na pusta; tutaj rejestr obejmuje ponad polowe zabudowy i od razu widac oba statusy.
 * Zoom musi byc >= POLYGON_MIN_ZOOM z layers.ts, inaczej backend wysyla same punkty.
 */
export const INITIAL_CENTER: [number, number] = [21.08, 51.25]
export const INITIAL_ZOOM = 15
export const MIN_ZOOM = 6
export const MAX_ZOOM = 20
