import type { RasterLayerSpecification, RasterSourceSpecification, StyleSpecification } from 'maplibre-gl'
import { ORTHOPHOTO_TILES_URL } from '../api/client'

/** Kafle OSM sa dobre na development. Przed publicznym demem potrzebujemy wlasnego zrodla. */
export const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
export const OSM_ATTRIBUTION = '© OpenStreetMap contributors'

/**
 * Ortofotomapa GUGiK idzie przez nasze proxy, bo urzad udostepnia tu WMS, nie WMTS — adres
 * szablonu trzymamy w jednym miejscu (`api/client.ts`), zeby nie rozjechal sie z backendem.
 * Atrybucja jest wymogiem regulaminu uslugi, wiec siedzi przy definicji podkladu, a nie
 * w komponencie, ktory ktos moze pominac.
 */
export const ORTHOPHOTO_ATTRIBUTION = 'Ortofotomapa: GUGiK / Geoportal.gov.pl'

/**
 * CARTO Positron: usluga zewnetrzna, darmowa pod warunkiem zachowania atrybucji. Przed publicznym
 * wdrozeniem trzeba sprawdzic jej regulamin (limity zapytan i warunki uzycia) — tak samo jak przy
 * kaflach OSM. MapLibre nie rozwija `{s}`, wiec trzy subdomeny podajemy jako trzy adresy
 * i biblioteka sama rozklada na nie ruch.
 */
export const CARTO_TILES = [
  'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
  'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
  'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
]
export const CARTO_ATTRIBUTION = '© OpenStreetMap contributors © CARTO'

/** Zadne z trzech zrodel rastrowych nie ma kafli powyzej 19 — wyzej MapLibre nadprobkuje. */
export const RASTER_MAX_ZOOM = 19

export const OSM_SOURCE_ID = 'osm'
export const ORTHOPHOTO_SOURCE_ID = 'orthophoto'
export const CARTO_SOURCE_ID = 'carto'

/**
 * Zrodla budujemy fabrykami, a nie jednym literalem na dwa style: MapLibre przy `setStyle` bierze
 * obiekt stylu na wlasnosc, wiec wspolne zrodlo oznaczaloby, ze jeden podklad dopisuje pola
 * do definicji drugiego.
 */
function osmSource(): RasterSourceSpecification {
  return {
    type: 'raster',
    tiles: [OSM_TILES],
    tileSize: 256,
    maxzoom: RASTER_MAX_ZOOM,
    attribution: OSM_ATTRIBUTION,
  }
}

function osmLayer(): RasterLayerSpecification {
  return { id: OSM_SOURCE_ID, type: 'raster', source: OSM_SOURCE_ID }
}

const standardStyle: StyleSpecification = {
  version: 8,
  sources: { [OSM_SOURCE_ID]: osmSource() },
  layers: [osmLayer()],
}

/**
 * Kafle poza zasiegiem nalotu wracaja przezroczyste, wiec OSM zostaje pod ortofoto: dziury
 * pokazuja wtedy mape, a nie czarne pole.
 */
const orthophotoStyle: StyleSpecification = {
  version: 8,
  sources: {
    [OSM_SOURCE_ID]: osmSource(),
    [ORTHOPHOTO_SOURCE_ID]: {
      type: 'raster',
      tiles: [ORTHOPHOTO_TILES_URL],
      tileSize: 256,
      maxzoom: RASTER_MAX_ZOOM,
      attribution: ORTHOPHOTO_ATTRIBUTION,
    },
  },
  layers: [osmLayer(), { id: ORTHOPHOTO_SOURCE_ID, type: 'raster', source: ORTHOPHOTO_SOURCE_ID }],
}

const minimalStyle: StyleSpecification = {
  version: 8,
  sources: {
    [CARTO_SOURCE_ID]: {
      type: 'raster',
      tiles: CARTO_TILES,
      tileSize: 256,
      maxzoom: RASTER_MAX_ZOOM,
      attribution: CARTO_ATTRIBUTION,
    },
  },
  layers: [{ id: CARTO_SOURCE_ID, type: 'raster', source: CARTO_SOURCE_ID }],
}

export type BasemapId = 'standard' | 'orthophoto' | 'minimal'

export type Basemap = {
  id: BasemapId
  /** Etykieta dla uzytkownika. Trzymamy ja przy stylu, zeby przelacznik nie mial wlasnej listy nazw. */
  label: string
  style: StyleSpecification
  /** Napis wymagany przez regulamin zrodla kafli — nigdy pusty. */
  attribution: string
}

export const BASEMAPS: Record<BasemapId, Basemap> = {
  standard: { id: 'standard', label: 'Mapa', style: standardStyle, attribution: OSM_ATTRIBUTION },
  orthophoto: {
    id: 'orthophoto',
    label: 'Ortofoto',
    style: orthophotoStyle,
    attribution: ORTHOPHOTO_ATTRIBUTION,
  },
  minimal: { id: 'minimal', label: 'Minimal', style: minimalStyle, attribution: CARTO_ATTRIBUTION },
}

/** Kolejnosc w przelaczniku: od najbardziej informacyjnego podkladu do najbardziej cichego. */
export const BASEMAP_IDS: BasemapId[] = ['standard', 'orthophoto', 'minimal']

export const DEFAULT_BASEMAP: BasemapId = 'standard'

/** Alias na styl domyslny — stare importy nie musza wiedziec o trzech podkladach. */
export const basemapStyle: StyleSpecification = standardStyle

/**
 * Okolice Zwolenia, nie Warszawa. W stolicy zgloszonych jest 0,1% budynkow, wiec mapa na starcie
 * wygladalaby na pusta; tutaj rejestr obejmuje ponad polowe zabudowy i od razu widac oba statusy.
 * Zoom musi byc >= POLYGON_MIN_ZOOM z layers.ts, inaczej backend wysyla same punkty.
 */
export const INITIAL_CENTER: [number, number] = [21.08, 51.25]
export const INITIAL_ZOOM = 15
export const MIN_ZOOM = 6
export const MAX_ZOOM = 20
