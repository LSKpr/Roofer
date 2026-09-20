import { expect, it } from 'vitest'
import { TILES_URL } from '../api/client'
import {
  CLICKABLE_LAYER_IDS,
  HIGHLIGHT_LAYER_IDS,
  LAYER_IDS,
  MAP_LAYERS,
  POINT_MIN_ZOOM,
  POINT_SOURCE_LAYER,
  POLYGON_MIN_ZOOM,
  POLYGON_SOURCE_LAYER,
  SOURCE_ID,
  SOURCE_MAX_ZOOM,
  STATUS_COLORS,
  buildingsFillLayer,
  buildingsSource,
  listedPointsLayer,
  selectedFillLayer,
  selectedFilter,
  selectedOutlineLayer,
} from './layers'

function channels(hex: string): [number, number, number] {
  const value = Number.parseInt(hex.slice(1), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

it('takes the tile template from the api client and stops overzooming at the last tile zoom', () => {
  expect(buildingsSource).toEqual({
    type: 'vector',
    tiles: [TILES_URL],
    minzoom: POINT_MIN_ZOOM,
    maxzoom: SOURCE_MAX_ZOOM,
  })
})

it('colours buildings by the listed attribute using both status colours', () => {
  expect(buildingsFillLayer.paint?.['fill-color']).toEqual([
    'case',
    ['get', 'listed'],
    STATUS_COLORS.listed,
    STATUS_COLORS.notListed,
  ])
  expect(STATUS_COLORS.listed).not.toBe(STATUS_COLORS.notListed)
})

it('never paints unlisted buildings green', () => {
  // Brak w rejestrze nie jest dowodem czystego dachu, wiec zielony jest zakazany.
  const [red, green, blue] = channels(STATUS_COLORS.notListed)
  expect(green).toBeLessThanOrEqual(Math.max(red, blue))
})

it('binds every layer to a tile layer the backend really produces', () => {
  expect(MAP_LAYERS.map((layer) => layer.id)).toEqual(Object.values(LAYER_IDS))
  for (const layer of MAP_LAYERS) {
    const source = 'source' in layer ? layer.source : undefined
    const sourceLayer = 'source-layer' in layer ? layer['source-layer'] : undefined
    expect(source).toBe(SOURCE_ID)
    expect([POLYGON_SOURCE_LAYER, POINT_SOURCE_LAYER]).toContain(sourceLayer)
  }
})

it('shows outlines only where the backend sends polygons', () => {
  expect(buildingsFillLayer.minzoom).toBe(POLYGON_MIN_ZOOM)
  expect(listedPointsLayer.minzoom).toBe(POINT_MIN_ZOOM)
  expect(listedPointsLayer['source-layer']).toBe(POINT_SOURCE_LAYER)
})

it('grows the listed point radius with zoom', () => {
  expect(listedPointsLayer.paint?.['circle-radius']).toEqual([
    'interpolate',
    ['linear'],
    ['zoom'],
    POINT_MIN_ZOOM,
    2,
    POLYGON_MIN_ZOOM,
    6,
  ])
  expect(listedPointsLayer.paint?.['circle-color']).toBe(STATUS_COLORS.listed)
})

it('matches nothing when no building is selected', () => {
  expect(selectedFilter(null)).toBe(false)
  expect(selectedFillLayer.filter).toBe(false)
  expect(selectedOutlineLayer.filter).toBe(false)
})

it('filters by feature id, not by an attribute', () => {
  expect(selectedFilter(7)).toEqual(['==', ['id'], 7])
  // ['get', 'id'] nie zadziala: w MVT identyfikator obiektu nie jest atrybutem.
  expect(JSON.stringify(selectedFilter(7))).not.toContain('get')
})

it('keeps the highlight above the data and out of the click targets', () => {
  const ids = MAP_LAYERS.map((layer) => layer.id)
  for (const highlight of HIGHLIGHT_LAYER_IDS) {
    for (const clickable of CLICKABLE_LAYER_IDS) {
      expect(ids.indexOf(highlight)).toBeGreaterThan(ids.indexOf(clickable))
    }
    expect(CLICKABLE_LAYER_IDS).not.toContain(highlight)
  }
})
