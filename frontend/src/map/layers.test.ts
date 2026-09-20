import { expect, it } from 'vitest'
import { TILES_URL } from '../api/client'
import {
  CLICKABLE_LAYER_IDS,
  DENSITY_COUNT_PROPERTY,
  DENSITY_MAX_ZOOM,
  DENSITY_SOURCE_LAYER,
  HEATMAP_MIN_WEIGHT,
  HEATMAP_RAMP,
  HEATMAP_RAMP_COLORS,
  HEATMAP_SATURATION_COUNT,
  HIGHLIGHT_LAYER_IDS,
  LAYER_IDS,
  MAP_LAYERS,
  POINT_MIN_ZOOM,
  POLYGON_MIN_ZOOM,
  POLYGON_SOURCE_LAYER,
  SOURCE_ID,
  SOURCE_MAX_ZOOM,
  STATUS_COLORS,
  buildingsFillLayer,
  buildingsOutlineLayer,
  buildingsSource,
  listedDensityLayer,
  selectedFillLayer,
  selectedFilter,
  selectedOutlineLayer,
} from './layers'

/** Zwraca kanaly RGB i alfe; przyjmuje i `#rrggbb`, i `rgba(r, g, b, a)`, bo rampa ma oba zapisy. */
function channels(color: string): [number, number, number, number] {
  if (color.startsWith('#')) {
    const value = Number.parseInt(color.slice(1), 16)
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255, 1]
  }
  const parts = color
    .replace(/^rgba?\(/, '')
    .replace(/\)$/, '')
    .split(',')
    .map((part) => Number(part.trim()))
  return [parts[0], parts[1], parts[2], parts[3] ?? 1]
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
    expect([POLYGON_SOURCE_LAYER, DENSITY_SOURCE_LAYER]).toContain(sourceLayer)
  }
})

// Kontrakt kafla: od zoomu 14 warstwa `buildings` z obrysami, nizej `listed_density`
// z komorkami siatki. Literowka w nazwie daje pusta mape bez jednego bledu w konsoli.
it('reads the density grid from the tile layer the backend names', () => {
  expect(DENSITY_SOURCE_LAYER).toBe('listed_density')
  expect(DENSITY_COUNT_PROPERTY).toBe('count')
  expect(listedDensityLayer.type).toBe('heatmap')
  expect(listedDensityLayer['source-layer']).toBe(DENSITY_SOURCE_LAYER)
  expect(listedDensityLayer.source).toBe(SOURCE_ID)
})

it('shows the heat exactly where the tile carries the grid and nowhere else', () => {
  expect(listedDensityLayer.minzoom).toBe(POINT_MIN_ZOOM)
  // `maxzoom` warstwy jest granica wylaczna, wiec cieplo konczy sie na DENSITY_MAX_ZOOM.
  expect(listedDensityLayer.maxzoom).toBe(POLYGON_MIN_ZOOM)
  expect(DENSITY_MAX_ZOOM).toBe(POLYGON_MIN_ZOOM - 1)
  expect(buildingsFillLayer.minzoom).toBe(POLYGON_MIN_ZOOM)
  expect(buildingsOutlineLayer.minzoom).toBe(POLYGON_MIN_ZOOM)
})

it('weighs every cell by its report count, not by the number of cells', () => {
  expect(listedDensityLayer.paint?.['heatmap-weight']).toEqual([
    'interpolate',
    ['linear'],
    ['get', DENSITY_COUNT_PROPERTY],
    1,
    HEATMAP_MIN_WEIGHT,
    HEATMAP_SATURATION_COUNT,
    1,
  ])
  // Komorka z jednym zgloszeniem musi byc widoczna, komorka z czterdziestoma — mocniejsza.
  expect(HEATMAP_MIN_WEIGHT).toBeGreaterThan(0)
  expect(HEATMAP_MIN_WEIGHT).toBeLessThan(1)
  expect(HEATMAP_SATURATION_COUNT).toBeGreaterThan(1)
})

it('scales radius and intensity with zoom, because a grid cell is not the same size at z8 and z13', () => {
  expect(listedDensityLayer.paint?.['heatmap-radius']).toEqual([
    'interpolate',
    ['linear'],
    ['zoom'],
    POINT_MIN_ZOOM,
    12,
    DENSITY_MAX_ZOOM,
    26,
  ])
  expect(listedDensityLayer.paint?.['heatmap-intensity']).toEqual([
    'interpolate',
    ['linear'],
    ['zoom'],
    POINT_MIN_ZOOM,
    0.6,
    DENSITY_MAX_ZOOM,
    1.8,
  ])
})

it('starts the colour ramp fully transparent so the map does not get a coloured wash', () => {
  const [density, color] = HEATMAP_RAMP[0]
  const [red, green, blue, alpha] = channels(color)
  expect(density).toBe(0)
  expect(alpha).toBe(0)
  // Ta sama czerwien co koniec rampy, tylko niewidoczna — inny odcien przebijalby na brzegach.
  expect([red, green, blue]).toEqual(channels(STATUS_COLORS.listed).slice(0, 3))
  expect(listedDensityLayer.paint?.['heatmap-color']).toEqual([
    'interpolate',
    ['linear'],
    ['heatmap-density'],
    ...HEATMAP_RAMP.flat(),
  ])
})

it('runs the ramp up to the registry red, through washed-out reds only', () => {
  const stops = HEATMAP_RAMP.map(([density]) => density)
  expect(stops).toEqual([...stops].sort((a, b) => a - b))
  expect(stops[stops.length - 1]).toBe(1)
  expect(HEATMAP_RAMP[HEATMAP_RAMP.length - 1][1]).toBe(STATUS_COLORS.listed)
})

it('keeps green and blue out of the heat ramp', () => {
  // Zielen znaczylaby „czysto", a mapa pokazuje wylacznie to, co ktos zglosil.
  for (const [, color] of HEATMAP_RAMP) {
    const [red, green, blue] = channels(color)
    expect(green).toBeLessThan(red)
    expect(blue).toBeLessThan(red)
  }
})

it('hands the legend the visible ramp stops, without the transparent one', () => {
  expect(HEATMAP_RAMP_COLORS).toEqual(HEATMAP_RAMP.slice(1).map(([, color]) => color))
  for (const color of HEATMAP_RAMP_COLORS) {
    expect(channels(color)[3]).toBe(1)
  }
})

// Test-straznik: komorka siatki nie ma identyfikatora budynku, wiec klik w nia wyslalby
// do /api/buildings/{id} liczbe zgloszen albo nic. Cieplo nie moze udawac budynku.
it('never makes the density grid clickable', () => {
  expect(CLICKABLE_LAYER_IDS).not.toContain(LAYER_IDS.density)
  expect(CLICKABLE_LAYER_IDS).toEqual([LAYER_IDS.fill])
  for (const layerId of CLICKABLE_LAYER_IDS) {
    const layer = MAP_LAYERS.find((candidate) => candidate.id === layerId)
    const sourceLayer = layer && 'source-layer' in layer ? layer['source-layer'] : undefined
    expect(sourceLayer).toBe(POLYGON_SOURCE_LAYER)
  }
})

it('draws building outlines above the heat', () => {
  const ids = MAP_LAYERS.map((layer) => layer.id)
  expect(ids.indexOf(LAYER_IDS.outline)).toBeGreaterThan(ids.indexOf(LAYER_IDS.density))
  expect(ids.indexOf(LAYER_IDS.fill)).toBeGreaterThan(ids.indexOf(LAYER_IDS.density))
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

// Podswietlamy budynek tylko tam, gdzie widac obrysy: na heatmapie nie ma czego podswietlic.
it('highlights only where the outlines are', () => {
  expect(selectedFillLayer.minzoom).toBe(POLYGON_MIN_ZOOM)
  expect(selectedOutlineLayer.minzoom).toBe(POLYGON_MIN_ZOOM)
  expect(selectedFillLayer['source-layer']).toBe(POLYGON_SOURCE_LAYER)
  expect(selectedOutlineLayer['source-layer']).toBe(POLYGON_SOURCE_LAYER)
})
