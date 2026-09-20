import { expect, it } from 'vitest'
import { TILES_URL } from '../api/client'
import {
  CLICKABLE_LAYER_IDS,
  DENSITY_COUNT_PROPERTY,
  FILL_OPACITY,
  LINE_WIDTH,
  NEUTRAL_FILL_OPACITY,
  NEUTRAL_LINE_WIDTH,
  fillOpacity,
  lineWidth,
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
  SCAN_AREA_FILL_OPACITY,
  SCAN_AREA_LAYER_IDS,
  SCAN_AREA_LAYERS,
  SCAN_AREA_LINE_WIDTH,
  SCAN_AREA_SOURCE_ID,
  SELECTED_COLOR,
  SOURCE_ID,
  SOURCE_MAX_ZOOM,
  STATUS_COLORS,
  SUSPECTED_COLOR,
  SUSPECTED_LAYER_IDS,
  SUSPECTED_LAYERS,
  SUSPECTED_LINE_WIDTH,
  SUSPECTED_SOURCE_ID,
  buildingsFillLayer,
  buildingsOutlineLayer,
  buildingsSource,
  fillColor,
  listedDensityLayer,
  outlineColor,
  scanAreaFillLayer,
  scanAreaOutlineLayer,
  selectedFillLayer,
  selectedFilter,
  selectedOutlineLayer,
  suspectedOutlineLayer,
  suspectedRoofsCollection,
} from './layers'
import type { SuspectedRoof } from './layers'
import { DRAW_LAYER_IDS, DRAW_SOURCE_ID, drawFillLayer, drawOutlineLayer } from './rectangleDraw'

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

// Przelacznik rejestru: wlaczony ma dawac dokladnie dzisiejsza mape, wiec warstwa i funkcja
// koloru musza byc jednym zrodlem prawdy. Dwie kopie wyrazenia rozjechalyby sie przy pierwszej
// zmianie palety.
it('builds the layer colours from the same function the toggle uses', () => {
  expect(buildingsFillLayer.paint?.['fill-color']).toEqual(fillColor(true))
  expect(buildingsOutlineLayer.paint?.['line-color']).toEqual(outlineColor(true))
})

it('keeps the listed case expression while the registry highlight is on', () => {
  const expression = ['case', ['get', 'listed'], STATUS_COLORS.listed, STATUS_COLORS.notListed]
  expect(fillColor(true)).toEqual(expression)
  expect(outlineColor(true)).toEqual(expression)
})

// Wylaczony przelacznik ma zdjac czerwien, a nie ja wyszarzyc: dopoki w kolorze siedzi
// `['get', 'listed']`, mapa dalej czyta rejestr i kazda zmiana palety przywroci roznice.
it('drops every reference to the listed attribute when the registry highlight is off', () => {
  expect(fillColor(false)).toBe(STATUS_COLORS.notListed)
  expect(outlineColor(false)).toBe(STATUS_COLORS.notListed)
  expect(JSON.stringify(fillColor(false))).not.toContain('listed')
  expect(JSON.stringify(outlineColor(false))).not.toContain('listed')
  expect(JSON.stringify(fillColor(false))).not.toContain('case')
  expect(JSON.stringify(fillColor(false))).not.toContain(STATUS_COLORS.listed)
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

// Trzy rodziny warstw zyja na jednej mapie: dane z kafla, podglad rysowania i policzony obszar.
// Wspolny identyfikator znaczylby, ze jedna po cichu nadpisuje druga.
it('keeps the scanned area ids disjoint from the tile layers and from the draw preview', () => {
  const ids = Object.values(SCAN_AREA_LAYER_IDS)
  expect(ids).toEqual([SCAN_AREA_LAYERS[0].id, SCAN_AREA_LAYERS[1].id])
  for (const id of [...ids, SCAN_AREA_SOURCE_ID]) {
    expect(Object.values(LAYER_IDS)).not.toContain(id)
    expect(Object.values(DRAW_LAYER_IDS)).not.toContain(id)
    expect(id).not.toBe(SOURCE_ID)
    expect(id).not.toBe(DRAW_SOURCE_ID)
  }
  // Obszar nie jest dana z kafla, wiec nie moze wejsc miedzy warstwy budynkow.
  expect(MAP_LAYERS.map((layer) => layer.id)).not.toContain(SCAN_AREA_LAYER_IDS.fill)
})

// Prostokat przykrywa wszystko, co zaznaczono. Klikalny zabralby kazde klikniecie budynkom.
it('never makes the scanned area clickable', () => {
  expect(CLICKABLE_LAYER_IDS).not.toContain(SCAN_AREA_LAYER_IDS.fill)
  expect(CLICKABLE_LAYER_IDS).not.toContain(SCAN_AREA_LAYER_IDS.outline)
  expect(HIGHLIGHT_LAYER_IDS).not.toContain(SCAN_AREA_LAYER_IDS.fill)
})

// Ramka podgladu mowi „trwa zaznaczanie", prostokat obszaru — „to jest obszar, ktorego dotycza
// liczby". Roznica jest w linii: przerywana wobec ciaglej. Gdyby obie byly takie same,
// uzytkownik nie wiedzialby, czy zaznaczenie sie skonczylo.
it('tells the scanned area apart from the draw preview by a solid line', () => {
  expect(drawOutlineLayer.paint?.['line-dasharray']).toBeDefined()
  expect(scanAreaOutlineLayer.paint?.['line-dasharray']).toBeUndefined()
  expect(scanAreaOutlineLayer.paint?.['line-width']).toBe(SCAN_AREA_LINE_WIDTH)
  expect(SCAN_AREA_LINE_WIDTH).toBeGreaterThanOrEqual(1.5)
  expect(SCAN_AREA_LINE_WIDTH).toBeLessThanOrEqual(2)
})

// Wypelnienie ma sygnalizowac obszar, a nie zamalowac wyniku: pod nim leza obrysy budynkow
// i ortofoto, ktore uzytkownik przyszedl ogladac.
it('keeps the scanned area fill light enough to read the buildings through it', () => {
  expect(scanAreaFillLayer.paint?.['fill-opacity']).toBe(SCAN_AREA_FILL_OPACITY)
  expect(SCAN_AREA_FILL_OPACITY).toBeGreaterThan(0)
  expect(SCAN_AREA_FILL_OPACITY).toBeLessThan(Number(drawFillLayer.paint?.['fill-opacity']))
})

// Kolor akcentu stoi w jednej stalej; drugi hex rozjechalby sie przy pierwszej zmianie motywu.
it('paints the scanned area with the accent colour from the shared constant', () => {
  expect(scanAreaFillLayer.paint?.['fill-color']).toBe(SELECTED_COLOR)
  expect(scanAreaOutlineLayer.paint?.['line-color']).toBe(SELECTED_COLOR)
  for (const layer of SCAN_AREA_LAYERS) {
    expect('source' in layer ? layer.source : undefined).toBe(SCAN_AREA_SOURCE_ID)
    // Zrodlo jest wlasne (GeoJSON z `Bounds`), wiec warstwa nie ma `source-layer` z kafla.
    expect('source-layer' in layer ? layer['source-layer'] : undefined).toBeUndefined()
  }
})

// Podswietlamy budynek tylko tam, gdzie widac obrysy: na heatmapie nie ma czego podswietlic.
it('highlights only where the outlines are', () => {
  expect(selectedFillLayer.minzoom).toBe(POLYGON_MIN_ZOOM)
  expect(selectedOutlineLayer.minzoom).toBe(POLYGON_MIN_ZOOM)
  expect(selectedFillLayer['source-layer']).toBe(POLYGON_SOURCE_LAYER)
  expect(selectedOutlineLayer['source-layer']).toBe(POLYGON_SOURCE_LAYER)
})

// Sam kolor to za malo: zgloszony budynek kryty 0,62 wobec 0,22 sasiada bylby nadal oznaczony,
// tylko innym srodkiem niz czerwien. Wylaczony przelacznik ma dawac mape jednolita.
it('drops opacity and line width differences too, not only the red', () => {
  expect(fillOpacity(true)).toBe(FILL_OPACITY)
  expect(lineWidth(true)).toBe(LINE_WIDTH)

  expect(fillOpacity(false)).toBe(NEUTRAL_FILL_OPACITY)
  expect(lineWidth(false)).toBe(NEUTRAL_LINE_WIDTH)
  // Zadnego odwolania do rejestru: liczba, nie wyrazenie po `listed`.
  expect(typeof fillOpacity(false)).toBe('number')
  expect(typeof lineWidth(false)).toBe('number')
})

it('leaves the map exactly as it looks today when the toggle is on', () => {
  // Stan domyslny nie moze sie zmienic przez dodanie przelacznika.
  expect(buildingsFillLayer.paint?.['fill-opacity']).toEqual(FILL_OPACITY)
  expect(buildingsOutlineLayer.paint?.['line-width']).toEqual(LINE_WIDTH)
  expect(NEUTRAL_FILL_OPACITY).toBe(0.22)
  expect(NEUTRAL_LINE_WIDTH).toBe(0.7)
})

/** Budynek z modelu; geometria taka, jaka oddaje ja backend — mapa nie ma jej przeliczac. */
const ROOF: SuspectedRoof = {
  id: 27469148,
  probability: 0.81,
  listed: false,
  areaM2: 126.6,
  geometry: {
    type: 'Polygon',
    coordinates: [
      [
        [21.0701, 51.2501],
        [21.0709, 51.2501],
        [21.0709, 51.2507],
        [21.0701, 51.2507],
        [21.0701, 51.2501],
      ],
    ],
  },
}

// Podejrzenie modelu to inna informacja niz wpis w rejestrze, wiec nie moze miec tego samego
// koloru; zielen jest zakazana z tego samego powodu co przy niezgloszonych budynkach.
it('paints the suspected roofs orange, far from the registry red and never green', () => {
  const [red, green, blue] = channels(SUSPECTED_COLOR)
  expect(SUSPECTED_COLOR).not.toBe(STATUS_COLORS.listed)
  expect(SUSPECTED_COLOR).not.toBe(STATUS_COLORS.notListed)
  expect(SUSPECTED_COLOR).not.toBe(SELECTED_COLOR)
  // Pomarancz: czerwony kanal prowadzi, zielony w srodku, niebieskiego prawie nie ma.
  expect(green).toBeLessThan(red)
  expect(blue).toBeLessThan(green)
  // Roznica wobec czerwieni rejestru musi byc widoczna, a nie tylko formalna — czerwien ma
  // zielony kanal przy zerze, pomarancz daleko od niego.
  expect(green - channels(STATUS_COLORS.listed)[1]).toBeGreaterThan(60)
})

// Obrys, nie wypelnienie: pod spodem musi zostac widoczny kolor rejestru (albo jego brak),
// bo najciekawszy jest szary budynek w pomaranczowej obwodce.
it('outlines the suspected roofs instead of filling them', () => {
  expect(SUSPECTED_LAYERS.map((layer) => layer.type)).toEqual(['line'])
  expect(SUSPECTED_LAYERS.map((layer) => layer.id)).toEqual(Object.values(SUSPECTED_LAYER_IDS))
  expect(suspectedOutlineLayer.paint?.['line-color']).toBe(SUSPECTED_COLOR)
  expect(JSON.stringify(SUSPECTED_LAYERS)).not.toContain('fill')
  // Zrodlo jest wlasne (GeoJSON z odpowiedzi modelu), wiec warstwa nie ma `source-layer` z kafla.
  expect(suspectedOutlineLayer.source).toBe(SUSPECTED_SOURCE_ID)
  expect(suspectedOutlineLayer['source-layer']).toBeUndefined()
})

// Cienka linia ginelaby na obrysie budynku, na ktorym lezy: obwodka ma byc widoczna od razu,
// takze na ortofoto.
it('draws the suspected outline clearly thicker than a building outline', () => {
  expect(suspectedOutlineLayer.paint?.['line-width']).toBe(SUSPECTED_LINE_WIDTH)
  expect(SUSPECTED_LINE_WIDTH).toBeGreaterThanOrEqual(2.5)
  expect(SUSPECTED_LINE_WIDTH).toBeLessThanOrEqual(3)
  // 1,2 px ma obrys zgloszonego budynku, 0,7 px pozostale — patrz LINE_WIDTH.
  expect(SUSPECTED_LINE_WIDTH).toBeGreaterThan(Number(LINE_WIDTH[2]))
  expect(SUSPECTED_LINE_WIDTH).toBeGreaterThan(NEUTRAL_LINE_WIDTH)
})

// Czwarta rodzina warstw na tej samej mapie. Wspolny identyfikator znaczylby, ze jedna po cichu
// nadpisuje druga — a wynik modelu potrafi stac na mapie razem z prostokatem skanu.
it('keeps the suspected ids disjoint from the tiles, the draw preview and the scanned area', () => {
  for (const id of [...Object.values(SUSPECTED_LAYER_IDS), SUSPECTED_SOURCE_ID]) {
    expect(Object.values(LAYER_IDS)).not.toContain(id)
    expect(Object.values(DRAW_LAYER_IDS)).not.toContain(id)
    expect(Object.values(SCAN_AREA_LAYER_IDS)).not.toContain(id)
    expect(id).not.toBe(SOURCE_ID)
    expect(id).not.toBe(DRAW_SOURCE_ID)
    expect(id).not.toBe(SCAN_AREA_SOURCE_ID)
  }
  // Wynik modelu nie jest dana z kafla, wiec nie wchodzi miedzy warstwy budynkow.
  expect(MAP_LAYERS.map((layer) => layer.id)).not.toContain(SUSPECTED_LAYER_IDS.outline)
})

// Test-straznik: obrys lezy dokladnie na budynku, wiec klikalny przejmowalby klikniecia.
// Karta budynku — z pelna ocena i nota modelu — otwiera sie z warstwy wypelnienia.
it('never makes the suspected outline clickable', () => {
  expect(CLICKABLE_LAYER_IDS).not.toContain(SUSPECTED_LAYER_IDS.outline)
  expect(CLICKABLE_LAYER_IDS).toEqual([LAYER_IDS.fill])
  expect(HIGHLIGHT_LAYER_IDS).not.toContain(SUSPECTED_LAYER_IDS.outline)
})

// Geometrie liczy model, nie mapa: ten sam obiekt ma trafic do zrodla, bez kopiowania
// i bez przeliczania wspolrzednych.
it('passes the model geometry into the collection untouched', () => {
  const collection = suspectedRoofsCollection([ROOF])

  expect(collection.type).toBe('FeatureCollection')
  expect(collection.features).toHaveLength(1)
  expect(collection.features[0].geometry).toBe(ROOF.geometry)
  expect(collection.features[0].id).toBe(ROOF.id)
  expect(collection.features[0].properties).toEqual({ probability: ROOF.probability })
})

it('carries a multipolygon through exactly as it arrived', () => {
  const geometry: SuspectedRoof['geometry'] = {
    type: 'MultiPolygon',
    coordinates: [[[[21.07, 51.25]]], [[[21.08, 51.26]]]],
  }
  const collection = suspectedRoofsCollection([{ ...ROOF, geometry }])

  expect(collection.features[0].geometry).toBe(geometry)
  expect(collection.features[0].geometry.type).toBe('MultiPolygon')
})

// „Model nic nie znalazl" to poprawna odpowiedz, a nie blad: kolekcja ma byc pusta, nie zepsuta.
it('turns an empty list into an empty collection', () => {
  expect(suspectedRoofsCollection([])).toEqual({ type: 'FeatureCollection', features: [] })
})

it('keeps one feature per roof, in the order the model gave them', () => {
  const second: SuspectedRoof = { ...ROOF, id: 28287777, probability: 0.52 }
  const collection = suspectedRoofsCollection([ROOF, second])

  expect(collection.features.map((feature) => feature.id)).toEqual([ROOF.id, second.id])
})
