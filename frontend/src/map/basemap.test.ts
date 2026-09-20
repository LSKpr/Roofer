import type { StyleSpecification } from 'maplibre-gl'
import { expect, it } from 'vitest'
import { ORTHOPHOTO_TILES_URL } from '../api/client'
import {
  BASEMAPS,
  BASEMAP_IDS,
  CARTO_TILES,
  DEFAULT_BASEMAP,
  OSM_SOURCE_ID,
  OSM_TILES,
  RASTER_MAX_ZOOM,
  basemapStyle,
} from './basemap'

function referencedSources(style: StyleSpecification): string[] {
  return style.layers.flatMap((layer) => ('source' in layer && layer.source ? [layer.source] : []))
}

it('uses the documented OpenStreetMap tile endpoint', () => {
  const source = basemapStyle.sources.osm
  expect(source.type).toBe('raster')
  expect(source.type === 'raster' && source.tiles).toEqual([OSM_TILES])
})

it('keeps the attribution that the tile usage policy requires', () => {
  const source = basemapStyle.sources.osm
  expect(source.type === 'raster' && source.attribution).toContain('OpenStreetMap')
})

it('has no layer pointing at a source that does not exist', () => {
  const declared = Object.keys(basemapStyle.sources)
  const referenced = referencedSources(basemapStyle)

  expect(referenced.length).toBeGreaterThan(0)
  for (const source of referenced) expect(declared).toContain(source)
})

it('offers exactly the three switchable basemaps', () => {
  expect(BASEMAP_IDS).toEqual(['standard', 'orthophoto', 'minimal'])
  expect(Object.keys(BASEMAPS).sort()).toEqual([...BASEMAP_IDS].sort())
  expect(BASEMAP_IDS).toContain(DEFAULT_BASEMAP)
})

it('starts on the plain map, because it is the only basemap without a third-party quota', () => {
  expect(DEFAULT_BASEMAP).toBe('standard')
  expect(BASEMAPS[DEFAULT_BASEMAP].style).toBe(basemapStyle)
})

it('keeps every basemap a valid style whose layers point at declared sources', () => {
  for (const id of BASEMAP_IDS) {
    const { style } = BASEMAPS[id]
    const declared = Object.keys(style.sources)

    expect(style.version).toBe(8)
    expect(declared.length).toBeGreaterThan(0)
    const referenced = referencedSources(style)
    expect(referenced.length).toBeGreaterThan(0)
    for (const source of referenced) expect(declared).toContain(source)
  }
})

it('keeps the id and label of every basemap in sync with its key', () => {
  for (const id of BASEMAP_IDS) {
    expect(BASEMAPS[id].id).toBe(id)
    expect(BASEMAPS[id].label.length).toBeGreaterThan(0)
  }
})

// Etykiety przelacznika zyja tylko tutaj (BasemapSwitcher czyta je z BASEMAPS), wiec to jedyne
// miejsce, w ktorym literowka albo powrot do polskiej nazwy zostanie zauwazona.
it('labels the switchable basemaps in the interface language', () => {
  expect(BASEMAP_IDS.map((id) => BASEMAPS[id].label)).toEqual(['Map', 'Aerial', 'Minimal'])
})

it('serves the orthophoto through our own proxy', () => {
  const source = BASEMAPS.orthophoto.style.sources.orthophoto
  expect(source.type).toBe('raster')
  expect(source.type === 'raster' && source.tiles).toEqual([ORTHOPHOTO_TILES_URL])
  expect(source.type === 'raster' && source.maxzoom).toBe(RASTER_MAX_ZOOM)
})

it('keeps OpenStreetMap under the orthophoto, so gaps in the flight show the map', () => {
  const { style } = BASEMAPS.orthophoto
  const order = style.layers.map((layer) => layer.id)

  expect(style.sources[OSM_SOURCE_ID]).toBeDefined()
  expect(order.indexOf(OSM_SOURCE_ID)).toBeGreaterThanOrEqual(0)
  expect(order.indexOf(OSM_SOURCE_ID)).toBeLessThan(order.indexOf('orthophoto'))
})

it('spreads the minimal basemap over the three CARTO subdomains', () => {
  const source = BASEMAPS.minimal.style.sources.carto
  expect(source.type === 'raster' && source.tiles).toEqual(CARTO_TILES)
  expect(CARTO_TILES).toHaveLength(3)
  expect(source.type === 'raster' && source.maxzoom).toBe(RASTER_MAX_ZOOM)
})

it('gives every basemap and every raster source a non-empty attribution', () => {
  for (const id of BASEMAP_IDS) {
    const basemap = BASEMAPS[id]
    expect(basemap.attribution.trim().length).toBeGreaterThan(0)

    for (const source of Object.values(basemap.style.sources)) {
      expect(source.type).toBe('raster')
      expect(source.type === 'raster' && (source.attribution ?? '').trim().length).toBeGreaterThan(0)
    }
  }
})

it('spells out the attribution that CARTO and GUGiK require', () => {
  expect(BASEMAPS.minimal.attribution).toBe('© OpenStreetMap contributors © CARTO')
  expect(BASEMAPS.orthophoto.attribution).toBe('Aerial imagery: GUGiK / Geoportal.gov.pl')

  const carto = BASEMAPS.minimal.style.sources.carto
  expect(carto.type === 'raster' && carto.attribution).toBe('© OpenStreetMap contributors © CARTO')
  const orthophoto = BASEMAPS.orthophoto.style.sources.orthophoto
  expect(orthophoto.type === 'raster' && orthophoto.attribution).toBe('Aerial imagery: GUGiK / Geoportal.gov.pl')
})
