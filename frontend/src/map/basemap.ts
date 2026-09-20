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

/** Warszawa: snapshoty danych obejmuja wojewodztwo mazowieckie. */
export const INITIAL_CENTER: [number, number] = [21.0, 52.23]
export const INITIAL_ZOOM = 10
export const MIN_ZOOM = 6
export const MAX_ZOOM = 20
