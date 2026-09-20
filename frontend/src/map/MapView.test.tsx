import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { Bounds } from '../api/client'
import { TILES_URL } from '../api/client'
import { BASEMAPS, DEFAULT_BASEMAP, INITIAL_CENTER, INITIAL_ZOOM, basemapStyle } from './basemap'
import {
  CHUNK_CURRENT_SOURCE_ID,
  CHUNK_DONE_SOURCE_ID,
  CHUNK_LAYER_IDS,
  CLICKABLE_LAYER_IDS,
  HIGHLIGHT_LAYER_IDS,
  LAYER_IDS,
  NEUTRAL_FILL_OPACITY,
  NEUTRAL_LINE_WIDTH,
  SCAN_AREA_LAYER_IDS,
  SCAN_AREA_SOURCE_ID,
  SOURCE_ID,
  SOURCE_MAX_ZOOM,
  STATUS_COLORS,
  SUSPECTED_LAYER_IDS,
  SUSPECTED_SOURCE_ID,
  fillColor,
  outlineColor,
} from './layers'
import type { SuspectedRoof } from './layers'
import { MapView } from './MapView'

type MapEvent = { point: { x: number; y: number } }
type Handler = (event: MapEvent) => void
type Feature = { id: number | string; layer: { id: string } }
/** Warstwa w atrapie trzyma swoje `paint` i `layout`, bo przelacznik rejestru zmienia wlasnie je. */
type AddedLayer = { id: string; type: string; paint?: Record<string, unknown>; layout?: Record<string, unknown> }
/** Tyle ze zrodla MapLibre, ile uzywa komponent: rodzaj, dane i podmiana danych w miejscu. */
type SourceEntry = { type?: string; data?: unknown; setData?: (data: unknown) => void }

const constructed: unknown[] = []
const added: unknown[] = []
const removed = vi.fn()
/** `sources` i `addedLayers` to stan mapy, nie dziennik: `setStyle` czysci je, tak jak MapLibre. */
const sources: Array<[string, unknown]> = []
const addedLayers: AddedLayer[] = []
const styleSwaps: Array<[unknown, unknown]> = []
const setFilters: Array<[string, unknown]> = []
const handlers: Array<{ type: string; layer?: string; handler: Handler }> = []
const queries: Array<[unknown, unknown]> = []
const canvasStyle = { cursor: '' }
/** Co ma zwrocic queryRenderedFeatures dla kolejnego klikniecia. */
let hits: Feature[] = []
const ZOOM = 15
/** Prostokat testowy; narozniki sa rozne w obu osiach, wiec zamiana lng z lat rzucalaby sie w oczy. */
const AREA: Bounds = { ne: { lng: 21.1, lat: 51.26 }, sw: { lng: 21.06, lat: 51.24 } }
const AREA_RING = [
  [21.06, 51.24],
  [21.1, 51.24],
  [21.1, 51.26],
  [21.06, 51.26],
  [21.06, 51.24],
]

/**
 * Podzial `AREA` na trzy kawalki, od zachodu na wschod — tak jak oddaje je `/api/area/plan`.
 * Pierscienie stoja obok nich doslownie, bo to one sa tym, co mapa naprawde ma narysowac.
 */
const CHUNKS: Bounds[] = [
  { ne: { lng: 21.08, lat: 51.26 }, sw: { lng: 21.06, lat: 51.24 } },
  { ne: { lng: 21.09, lat: 51.26 }, sw: { lng: 21.08, lat: 51.24 } },
  { ne: { lng: 21.1, lat: 51.26 }, sw: { lng: 21.09, lat: 51.24 } },
]
const CHUNK_RINGS = [
  [
    [21.06, 51.24],
    [21.08, 51.24],
    [21.08, 51.26],
    [21.06, 51.26],
    [21.06, 51.24],
  ],
  [
    [21.08, 51.24],
    [21.09, 51.24],
    [21.09, 51.26],
    [21.08, 51.26],
    [21.08, 51.24],
  ],
  [
    [21.09, 51.24],
    [21.1, 51.24],
    [21.1, 51.26],
    [21.09, 51.26],
    [21.09, 51.24],
  ],
]

/**
 * Budynek z modelu. Geometria przychodzi z backendu gotowa, wiec test podaje ja doslownie
 * i sprawdza, ze mapa oddaje dokladnie te wspolrzedne — nie przeliczone, nie z `Bounds`.
 */
const ROOF_GEOMETRY = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [21.0701, 51.2501],
      [21.0709, 51.2501],
      [21.0709, 51.2507],
      [21.0701, 51.2507],
      [21.0701, 51.2501],
    ],
  ],
}
/** Niezgloszony, a model widzi eternit — przypadek, dla ktorego ta warstwa w ogole powstala. */
const ROOF: SuspectedRoof = {
  id: 27469148,
  probability: 0.81,
  listed: false,
  areaM2: 126.6,
  geometry: ROOF_GEOMETRY,
}
const OTHER_ROOF: SuspectedRoof = {
  id: 28287777,
  probability: 0.64,
  listed: true,
  areaM2: 67.9,
  geometry: { type: 'Polygon', coordinates: [[[20.4, 52.2]]] },
}

/**
 * Zrodlo GeoJSON w atrapie naprawde trzyma dane: `setData` nadpisuje `data`, tak jak w MapLibre.
 * Atrapa, ktora tylko przyjmuje wywolanie, nie odroznilaby ustawionej geometrii od jej braku.
 * Zrodla kaflowe zostaja takie, jakie przyszly — nie maja `setData`.
 */
function sourceEntry(spec: unknown): unknown {
  const entry: SourceEntry = { ...(spec as SourceEntry) }
  if (entry.type !== 'geojson') return spec
  entry.setData = (data: unknown) => {
    entry.data = data
  }
  return entry
}

/** Dane, ktore zrodlo ma teraz — po dodaniu albo po ostatnim `setData`. */
function sourceData(id: string): unknown {
  const entry = sources.find(([sourceId]) => sourceId === id)?.[1] as SourceEntry | undefined
  return entry?.data
}

function layerIds(): string[] {
  return addedLayers.map((layer) => layer.id)
}

/** Aktualna wartosc wlasciwosci malowania — po dodaniu warstwy albo po `setPaintProperty`. */
function paintOf(id: string, property: string): unknown {
  return addedLayers.find((layer) => layer.id === id)?.paint?.[property]
}

function layoutOf(id: string, property: string): unknown {
  return addedLayers.find((layer) => layer.id === id)?.layout?.[property]
}

// jsdom nie ma WebGL, wiec cala MapLibre jest podmieniona; mock zapisuje, co komponent zrobil z mapa.
vi.mock('maplibre-gl', () => ({
  Map: class {
    constructor(options: unknown) {
      constructed.push(options)
    }
    addControl(control: unknown) {
      added.push(control)
    }
    on(type: string, layerOrHandler: string | Handler, maybeHandler?: Handler) {
      if (typeof layerOrHandler === 'string') {
        handlers.push({ type, layer: layerOrHandler, handler: maybeHandler as Handler })
      } else {
        handlers.push({ type, handler: layerOrHandler })
      }
    }
    // Rysowanie prostokata (rectangleDraw) odczepia sie po zakonczeniu i przy odmontowaniu,
    // wiec mock musi naprawde usuwac nasluchy — inaczej testy liczace handlery klamalyby.
    off(type: string, layerOrHandler: string | Handler, maybeHandler?: Handler) {
      const handler = typeof layerOrHandler === 'string' ? maybeHandler : layerOrHandler
      const index = handlers.findIndex((entry) => entry.type === type && entry.handler === handler)
      if (index >= 0) handlers.splice(index, 1)
    }
    addSource(id: string, spec: unknown) {
      sources.push([id, sourceEntry(spec)])
    }
    removeSource(id: string) {
      const index = sources.findIndex(([sourceId]) => sourceId === id)
      if (index >= 0) sources.splice(index, 1)
    }
    removeLayer(id: string) {
      const index = addedLayers.findIndex((layer) => layer.id === id)
      if (index >= 0) addedLayers.splice(index, 1)
    }
    getSource(id: string) {
      return sources.find(([sourceId]) => sourceId === id)?.[1]
    }
    // Kopia, nie referencja: warstwa na mapie ma zyc wlasnym zyciem, a `setPaintProperty`
    // na wspoldzielonym obiekcie nadpisywaloby definicje warstwy z layers.ts na caly plik testow.
    //
    // `beforeId` wstawia warstwe POD wskazana, tak jak w MapLibre: bez tego mock zawsze dokladalby
    // na wierzch i test kolejnosci nie odroznilby warstwy pod podswietleniem od warstwy nad nim.
    addLayer(layer: AddedLayer, beforeId?: string) {
      const index = beforeId === undefined ? -1 : addedLayers.findIndex((entry) => entry.id === beforeId)
      if (index >= 0) addedLayers.splice(index, 0, { ...layer })
      else addedLayers.push({ ...layer })
    }
    getLayer(id: string) {
      return addedLayers.find((layer) => layer.id === id)
    }
    // Obie musza naprawde zapisywac: atrapa, ktora tylko przyjmuje wywolanie, nie odroznilaby
    // ustawionego koloru od jego braku i testy przelacznika niczego by nie dowodzily.
    setPaintProperty(id: string, property: string, value: unknown) {
      const layer = addedLayers.find((entry) => entry.id === id)
      if (!layer) throw new Error(`setPaintProperty na nieistniejacej warstwie ${id}`)
      layer.paint = { ...layer.paint, [property]: value }
    }
    setLayoutProperty(id: string, property: string, value: unknown) {
      const layer = addedLayers.find((entry) => entry.id === id)
      if (!layer) throw new Error(`setLayoutProperty na nieistniejacej warstwie ${id}`)
      layer.layout = { ...layer.layout, [property]: value }
    }
    // Prawdziwa MapLibre razem ze starym stylem usuwa zrodla i warstwy dodane recznie,
    // a potem wysyla `style.load`. Mock musi robic to samo, inaczej test nie zauwazylby,
    // ze komponent ich nie odtwarza.
    setStyle(style: unknown, options: unknown) {
      styleSwaps.push([style, options])
      sources.length = 0
      addedLayers.length = 0
    }
    setFilter(id: string, filter: unknown) {
      setFilters.push([id, filter])
    }
    queryRenderedFeatures(point: unknown, options: unknown) {
      queries.push([point, options])
      return hits
    }
    getCanvas() {
      return { style: canvasStyle }
    }
    getZoom() {
      return ZOOM
    }
    remove = removed
  },
  NavigationControl: class {},
  ScaleControl: class {},
}))

function fire(type: string, layer?: string) {
  for (const entry of handlers.filter((item) => item.type === type && item.layer === layer)) {
    entry.handler({ point: { x: 10, y: 20 } })
  }
}

beforeEach(() => {
  constructed.length = 0
  added.length = 0
  sources.length = 0
  addedLayers.length = 0
  styleSwaps.length = 0
  setFilters.length = 0
  handlers.length = 0
  queries.length = 0
  canvasStyle.cursor = ''
  hits = []
  removed.mockClear()
})

it('creates one map with the configured style and viewport', () => {
  render(<MapView />)

  expect(screen.getByTestId('map')).toBeDefined()
  expect(constructed).toHaveLength(1)
  expect(constructed[0]).toMatchObject({ style: basemapStyle, center: INITIAL_CENTER, zoom: INITIAL_ZOOM })
  expect(added).toHaveLength(2)
})

it('adds the building tile source once the style is loaded', () => {
  render(<MapView />)
  fire('style.load')

  expect(sources).toHaveLength(1)
  expect(sources[0][0]).toBe(SOURCE_ID)
  expect(sources[0][1]).toMatchObject({ type: 'vector', tiles: [TILES_URL], maxzoom: SOURCE_MAX_ZOOM })
})

it('adds every layer in the documented order', () => {
  render(<MapView />)
  fire('style.load')

  expect(addedLayers.map((layer) => layer.id)).toEqual(Object.values(LAYER_IDS))
  expect(addedLayers).toHaveLength(5)
  // Cieplo idzie na spod, obrysy budynkow nad nie: MapLibre rysuje w kolejnosci dodawania.
  const ids = addedLayers.map((layer) => layer.id)
  expect(ids.indexOf(LAYER_IDS.outline)).toBeGreaterThan(ids.indexOf(LAYER_IDS.density))
})

it('selects the clicked building', () => {
  const onSelect = vi.fn()
  render(<MapView selectedId={null} onSelect={onSelect} />)
  fire('style.load')
  hits = [{ id: 42, layer: { id: LAYER_IDS.fill } }]
  fire('click')

  expect(queries[0][1]).toEqual({ layers: CLICKABLE_LAYER_IDS })
  expect(onSelect).toHaveBeenCalledWith(42)
})

// MVT potrafi oddac identyfikator jako napis, a /api/buildings/{id} przyjmuje liczbe.
it('passes a string feature id on as a number', () => {
  const onSelect = vi.fn()
  render(<MapView selectedId={null} onSelect={onSelect} />)
  fire('style.load')
  hits = [{ id: '7', layer: { id: LAYER_IDS.fill } }]
  fire('click')

  expect(onSelect).toHaveBeenCalledWith(7)
})

// Komorka siatki gestosci nie jest budynkiem i nie ma identyfikatora, wiec nie moze byc celem
// klikniecia ani zmieniac kursora na „klikalny" — inaczej mapa obiecywalaby karte budynku,
// ktorej nie ma.
it('never queries the density grid and never puts a pointer cursor over it', () => {
  render(<MapView />)
  fire('style.load')
  fire('click')

  expect(queries[0][1]).toEqual({ layers: [LAYER_IDS.fill] })
  expect(handlers.filter((entry) => entry.layer === LAYER_IDS.density)).toHaveLength(0)
})

it('clears the selection when the click hits no feature', () => {
  const onSelect = vi.fn()
  render(<MapView selectedId={7} onSelect={onSelect} />)
  fire('style.load')
  fire('click')

  expect(onSelect).toHaveBeenCalledWith(null)
})

it('sets the cursor over clickable layers', () => {
  render(<MapView />)
  fire('style.load')
  fire('mouseenter', LAYER_IDS.fill)
  expect(canvasStyle.cursor).toBe('pointer')

  fire('mouseleave', LAYER_IDS.fill)
  expect(canvasStyle.cursor).toBe('')
})

it('filters the highlight layers when selectedId changes', () => {
  const view = render(<MapView selectedId={null} />)
  fire('style.load')
  setFilters.length = 0

  view.rerender(<MapView selectedId={7} />)

  expect(setFilters).toEqual(HIGHLIGHT_LAYER_IDS.map((id) => [id, ['==', ['id'], 7]]))
  expect(constructed).toHaveLength(1)
})

it('reports the zoom after loading and after zooming', () => {
  const onZoomChange = vi.fn()
  render(<MapView onZoomChange={onZoomChange} />)
  fire('style.load')
  expect(onZoomChange).toHaveBeenCalledWith(ZOOM)

  onZoomChange.mockClear()
  fire('zoomend')
  expect(onZoomChange).toHaveBeenCalledWith(ZOOM)
})

it('removes the map when the component unmounts', () => {
  const view = render(<MapView />)
  view.unmount()

  expect(removed).toHaveBeenCalled()
})

// Mapa dostaje pierwszy styl w konstruktorze, wiec `setStyle` na starcie byloby drugim
// zaladowaniem tych samych kafli.
it('does not swap the style on the first render', () => {
  render(<MapView />)
  fire('style.load')

  expect(styleSwaps).toHaveLength(0)
  expect(constructed).toHaveLength(1)
  expect(constructed[0]).toMatchObject({ style: BASEMAPS[DEFAULT_BASEMAP].style })
})

it('swaps only the style when the basemap prop changes', () => {
  const view = render(<MapView basemap="standard" />)
  fire('style.load')

  view.rerender(<MapView basemap="orthophoto" />)

  expect(styleSwaps).toEqual([[BASEMAPS.orthophoto.style, { diff: false }]])
  // Zmiana podkladu nie moze przebudowac mapy: kamera i nasluchy musza zostac.
  expect(constructed).toHaveLength(1)
})

// MapLibre razem ze starym stylem usuwa zrodla i warstwy dodane recznie — mock robi to samo,
// wiec ten test wykrylby brak odtworzenia warstw budynkow po podmianie podkladu.
it('re-adds the building source and layers after a style swap', () => {
  const view = render(<MapView basemap="standard" />)
  fire('style.load')

  view.rerender(<MapView basemap="minimal" />)
  expect(sources).toHaveLength(0)
  expect(addedLayers).toHaveLength(0)

  fire('style.load')

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])
  expect(addedLayers.map((layer) => layer.id)).toEqual(Object.values(LAYER_IDS))
})

it('restores the highlight of the selected building after a style swap', () => {
  const view = render(<MapView selectedId={7} basemap="standard" />)
  fire('style.load')
  view.rerender(<MapView selectedId={7} basemap="orthophoto" />)
  setFilters.length = 0

  fire('style.load')

  expect(setFilters).toEqual(HIGHLIGHT_LAYER_IDS.map((id) => [id, ['==', ['id'], 7]]))
})

// Nasluchy kursora siedza na mapie, nie na stylu, wiec drugi `style.load` nie moze ich dolozyc:
// dwa zestawy tych samych handlerow to dwa wywolania na kazde przejscie myszka.
it('binds the cursor handlers once, not on every style load', () => {
  const view = render(<MapView basemap="standard" />)
  fire('style.load')

  view.rerender(<MapView basemap="minimal" />)
  fire('style.load')

  const enters = handlers.filter((entry) => entry.type === 'mouseenter' && entry.layer === LAYER_IDS.fill)
  expect(enters).toHaveLength(1)
})

// Zeskanowany obszar jest stanem aplikacji, nie interakcji z myszka: rysuje go prop, wiec prostokat
// zostaje na mapie po puszczeniu przycisku, kiedy przerywana ramka podgladu juz znikla.
it('draws the scanned rectangle from its own source, above the buildings', () => {
  render(<MapView scannedArea={AREA} />)
  fire('style.load')

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID, SCAN_AREA_SOURCE_ID])
  expect(sourceData(SCAN_AREA_SOURCE_ID)).toEqual({
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [AREA_RING] },
  })
  // Nad warstwami budynkow: MapLibre rysuje w kolejnosci dodawania, a obrys obszaru ma byc widoczny.
  expect(layerIds()).toEqual([...Object.values(LAYER_IDS), ...Object.values(SCAN_AREA_LAYER_IDS)])
})

it('draws a rectangle that arrives after the style has loaded', () => {
  const view = render(<MapView />)
  fire('style.load')
  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])

  view.rerender(<MapView scannedArea={AREA} />)

  expect(sourceData(SCAN_AREA_SOURCE_ID)).toMatchObject({ geometry: { coordinates: [AREA_RING] } })
  expect(layerIds()).toContain(SCAN_AREA_LAYER_IDS.outline)
})

// Nowy skan przesuwa ten sam prostokat. Usuwanie i dodawanie zrodla zabieraloby ze soba warstwy.
it('moves the rectangle to the new area without duplicating the source or the layers', () => {
  const view = render(<MapView scannedArea={AREA} />)
  fire('style.load')

  const next: Bounds = { ne: { lng: 20.5, lat: 52.3 }, sw: { lng: 20.4, lat: 52.2 } }
  view.rerender(<MapView scannedArea={next} />)

  expect(sourceData(SCAN_AREA_SOURCE_ID)).toMatchObject({
    geometry: {
      coordinates: [
        [
          [20.4, 52.2],
          [20.5, 52.2],
          [20.5, 52.3],
          [20.4, 52.3],
          [20.4, 52.2],
        ],
      ],
    },
  })
  expect(sources.filter(([id]) => id === SCAN_AREA_SOURCE_ID)).toHaveLength(1)
  expect(layerIds().filter((id) => id === SCAN_AREA_LAYER_IDS.fill)).toHaveLength(1)
})

// Zamkniecie panelu wyniku ma zdjac prostokat z mapy, a nie zostawic pustej warstwy.
it('takes the rectangle off the map when the area goes back to null', () => {
  const view = render(<MapView scannedArea={AREA} />)
  fire('style.load')

  view.rerender(<MapView scannedArea={null} />)

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])
  expect(layerIds()).toEqual(Object.values(LAYER_IDS))
})

// `setStyle` zabiera wszystko dodane recznie. Wynik skanu przezywa zmiane podkladu, wiec jego
// obszar tez musi wrocic — razem z geometria, nie jako pusta warstwa.
it('brings the scanned rectangle back after a basemap swap', () => {
  const view = render(<MapView scannedArea={AREA} basemap="standard" />)
  fire('style.load')

  view.rerender(<MapView scannedArea={AREA} basemap="orthophoto" />)
  expect(sources).toHaveLength(0)
  expect(addedLayers).toHaveLength(0)

  fire('style.load')

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID, SCAN_AREA_SOURCE_ID])
  expect(sourceData(SCAN_AREA_SOURCE_ID)).toMatchObject({ geometry: { coordinates: [AREA_RING] } })
  expect(layerIds()).toEqual([...Object.values(LAYER_IDS), ...Object.values(SCAN_AREA_LAYER_IDS)])
})

// Prostokat przykrywa cale zaznaczenie, wiec gdyby byl klikalny, kazdy klik w obszar udawalby
// klik w budynek — i karta budynku otwieralaby sie dla niewlasciwego obiektu albo dla zadnego.
it('never lets a click on the scanned area pass as a click on a building', () => {
  const onSelect = vi.fn()
  render(<MapView scannedArea={AREA} onSelect={onSelect} />)
  fire('style.load')
  fire('click')

  expect(queries[0][1]).toEqual({ layers: [LAYER_IDS.fill] })
  expect(CLICKABLE_LAYER_IDS).not.toContain(SCAN_AREA_LAYER_IDS.fill)
  expect(CLICKABLE_LAYER_IDS).not.toContain(SCAN_AREA_LAYER_IDS.outline)
  expect(onSelect).toHaveBeenCalledWith(null)
})

// Przelacznik rejestru. Domyslnie wlaczony, wiec mapa startuje dokladnie tak jak dotad:
// zgloszone na czerwono, cieplo widoczne.
it('keeps the registry highlight on by default', () => {
  render(<MapView />)
  fire('style.load')

  expect(paintOf(LAYER_IDS.fill, 'fill-color')).toEqual(fillColor(true))
  expect(paintOf(LAYER_IDS.outline, 'line-color')).toEqual(outlineColor(true))
  expect(layoutOf(LAYER_IDS.density, 'visibility')).toBe('visible')
})

it('paints every building in the neutral colour and hides the heat when the highlight is off', () => {
  const view = render(<MapView />)
  fire('style.load')

  view.rerender(<MapView showRegistry={false} />)

  expect(paintOf(LAYER_IDS.fill, 'fill-color')).toBe(STATUS_COLORS.notListed)
  expect(paintOf(LAYER_IDS.outline, 'line-color')).toBe(STATUS_COLORS.notListed)
  expect(layoutOf(LAYER_IDS.density, 'visibility')).toBe('none')
  // Krycie i grubosc tez, bo inaczej zgloszony budynek zostalby oznaczony ciemniejsza szaroscia
  // (0,62 wobec 0,22) — przelacznik zdjalby czerwien, a nie oznaczenie.
  expect(paintOf(LAYER_IDS.fill, 'fill-opacity')).toBe(NEUTRAL_FILL_OPACITY)
  expect(paintOf(LAYER_IDS.outline, 'line-width')).toBe(NEUTRAL_LINE_WIDTH)
})

it('brings the red and the heat back when the highlight goes on again', () => {
  const view = render(<MapView showRegistry={false} />)
  fire('style.load')

  view.rerender(<MapView showRegistry />)

  expect(paintOf(LAYER_IDS.fill, 'fill-color')).toEqual(fillColor(true))
  expect(paintOf(LAYER_IDS.outline, 'line-color')).toEqual(outlineColor(true))
  expect(layoutOf(LAYER_IDS.density, 'visibility')).toBe('visible')
})

// Warstwa wypelnienia jest jedynym celem klikniec, wiec wylaczone podswietlenie nie moze jej
// schowac — uzytkownik stracilby mozliwosc otwarcia karty budynku.
it('never hides the fill layer, because it is the only click target', () => {
  render(<MapView showRegistry={false} />)
  fire('style.load')

  expect(layerIds()).toContain(LAYER_IDS.fill)
  expect(layoutOf(LAYER_IDS.fill, 'visibility')).toBeUndefined()
  expect(layoutOf(LAYER_IDS.outline, 'visibility')).toBeUndefined()
})

it('still opens a building when the registry highlight is off', () => {
  const onSelect = vi.fn()
  render(<MapView showRegistry={false} onSelect={onSelect} />)
  fire('style.load')
  hits = [{ id: 42, layer: { id: LAYER_IDS.fill } }]
  fire('click')

  expect(queries[0][1]).toEqual({ layers: [LAYER_IDS.fill] })
  expect(onSelect).toHaveBeenCalledWith(42)
})

// `setStyle` zabiera warstwy dodane recznie, a wracaja one w stanie domyslnym — czyli
// z czerwienia. Bez ponownego nalozenia przelacznika zmiana podkladu po cichu wlaczalaby
// podswietlenie, ktore uzytkownik wylaczyl.
it('keeps the registry highlight off after a basemap swap', () => {
  const view = render(<MapView showRegistry={false} basemap="standard" />)
  fire('style.load')

  view.rerender(<MapView showRegistry={false} basemap="orthophoto" />)
  expect(addedLayers).toHaveLength(0)

  fire('style.load')

  expect(paintOf(LAYER_IDS.fill, 'fill-color')).toBe(STATUS_COLORS.notListed)
  expect(paintOf(LAYER_IDS.outline, 'line-color')).toBe(STATUS_COLORS.notListed)
  expect(layoutOf(LAYER_IDS.density, 'visibility')).toBe('none')
})

// Warstwa podejrzen modelu. Obrys idzie nad budynki (inaczej wypelnienie by go przykrylo),
// ale pod podswietlenie wyboru: klikniety budynek ma zostac najmocniejsza rzecza na mapie.
it('draws the suspected roofs from their own source, above the buildings and under the highlight', () => {
  render(<MapView suspectedRoofs={[ROOF]} />)
  fire('style.load')

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID, SUSPECTED_SOURCE_ID])
  expect(sourceData(SUSPECTED_SOURCE_ID)).toEqual({
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        id: ROOF.id,
        properties: { probability: ROOF.probability },
        geometry: ROOF_GEOMETRY,
      },
    ],
  })
  const ids = layerIds()
  expect(ids.indexOf(SUSPECTED_LAYER_IDS.outline)).toBeGreaterThan(ids.indexOf(LAYER_IDS.outline))
  expect(ids.indexOf(SUSPECTED_LAYER_IDS.outline)).toBeLessThan(ids.indexOf(LAYER_IDS.selectedFill))
})

// Zwykla kolej rzeczy: mapa stoi, uzytkownik puszcza obszar przez model i dopiero wtedy
// przychodza wyniki. Miejsce w stosie musi byc to samo co po zaladowaniu stylu.
it('draws roofs that arrive after the style has loaded, still under the highlight', () => {
  const view = render(<MapView />)
  fire('style.load')
  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])

  view.rerender(<MapView suspectedRoofs={[ROOF]} />)

  expect(sourceData(SUSPECTED_SOURCE_ID)).toMatchObject({ features: [{ geometry: ROOF_GEOMETRY }] })
  const ids = layerIds()
  expect(ids.indexOf(SUSPECTED_LAYER_IDS.outline)).toBeGreaterThan(ids.indexOf(LAYER_IDS.fill))
  expect(ids.indexOf(SUSPECTED_LAYER_IDS.outline)).toBeLessThan(ids.indexOf(LAYER_IDS.selectedOutline))
})

// Kolejny przebieg modelu podmienia zawartosc warstwy. Usuwanie i dodawanie zrodla zabieraloby
// ze soba warstwe i mrugaloby obrysami przy kazdym wyniku.
it('replaces the suspected roofs without duplicating the source or the layer', () => {
  const view = render(<MapView suspectedRoofs={[ROOF]} />)
  fire('style.load')

  view.rerender(<MapView suspectedRoofs={[OTHER_ROOF]} />)

  expect(sourceData(SUSPECTED_SOURCE_ID)).toMatchObject({
    features: [{ id: OTHER_ROOF.id, geometry: OTHER_ROOF.geometry }],
  })
  expect(sources.filter(([id]) => id === SUSPECTED_SOURCE_ID)).toHaveLength(1)
  expect(layerIds().filter((id) => id === SUSPECTED_LAYER_IDS.outline)).toHaveLength(1)
})

// Pusta lista to odpowiedz modelu „nic tu nie widze", a nie brak wyniku: warstwa zostaje,
// tylko bez obiektow — inaczej nastepny wynik musialby ja stawiac od zera.
it('keeps an empty layer when the model returns nothing', () => {
  render(<MapView suspectedRoofs={[]} />)
  fire('style.load')

  expect(sourceData(SUSPECTED_SOURCE_ID)).toEqual({ type: 'FeatureCollection', features: [] })
  expect(layerIds()).toContain(SUSPECTED_LAYER_IDS.outline)
})

it('takes the suspected outlines off the map when the list goes back to null', () => {
  const view = render(<MapView suspectedRoofs={[ROOF]} />)
  fire('style.load')

  view.rerender(<MapView suspectedRoofs={null} />)

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])
  expect(layerIds()).toEqual(Object.values(LAYER_IDS))
})

// `setStyle` zabiera wszystko dodane recznie. Wynik modelu nie znika przez to, ze uzytkownik
// przelaczyl podklad — ma wrocic razem z geometria i na to samo miejsce w stosie.
it('brings the suspected outlines back after a basemap swap', () => {
  const view = render(<MapView suspectedRoofs={[ROOF]} basemap="standard" />)
  fire('style.load')

  view.rerender(<MapView suspectedRoofs={[ROOF]} basemap="orthophoto" />)
  expect(sources).toHaveLength(0)
  expect(addedLayers).toHaveLength(0)

  fire('style.load')

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID, SUSPECTED_SOURCE_ID])
  expect(sourceData(SUSPECTED_SOURCE_ID)).toMatchObject({ features: [{ geometry: ROOF_GEOMETRY }] })
  const ids = layerIds()
  expect(ids.indexOf(SUSPECTED_LAYER_IDS.outline)).toBeGreaterThan(ids.indexOf(LAYER_IDS.outline))
  expect(ids.indexOf(SUSPECTED_LAYER_IDS.outline)).toBeLessThan(ids.indexOf(LAYER_IDS.selectedFill))
})

// Test-straznik: obrys modelu lezy dokladnie na budynku, wiec klikalny przejmowalby kazde
// klikniecie w niego. Karta budynku (z pelna ocena i nota) otwiera sie z warstwy wypelnienia.
it('never lets a click on a suspected outline pass as a click on a building', () => {
  const onSelect = vi.fn()
  render(<MapView suspectedRoofs={[ROOF]} onSelect={onSelect} />)
  fire('style.load')
  hits = [{ id: ROOF.id, layer: { id: LAYER_IDS.fill } }]
  fire('click')

  expect(queries[0][1]).toEqual({ layers: [LAYER_IDS.fill] })
  expect(CLICKABLE_LAYER_IDS).not.toContain(SUSPECTED_LAYER_IDS.outline)
  // Klik trafia w budynek pod spodem, a nie w obrys nad nim.
  expect(onSelect).toHaveBeenCalledWith(ROOF.id)
  expect(handlers.filter((entry) => entry.layer === SUSPECTED_LAYER_IDS.outline)).toHaveLength(0)
})

// Sedno warstwy: „jest w rejestrze" i „model cos widzi" to dwie rozne informacje i musza dac sie
// odczytac na tym samym budynku. Obrys nie moze niczego zabrac wypelnieniu ani cieplu.
it('leaves the registry colours untouched under the suspected outlines', () => {
  const view = render(<MapView />)
  fire('style.load')

  view.rerender(<MapView suspectedRoofs={[ROOF]} />)

  expect(paintOf(LAYER_IDS.fill, 'fill-color')).toEqual(fillColor(true))
  expect(paintOf(LAYER_IDS.outline, 'line-color')).toEqual(outlineColor(true))
  expect(layoutOf(LAYER_IDS.density, 'visibility')).toBe('visible')
  expect(layerIds()).toContain(LAYER_IDS.fill)
})

/** Prostokat kawalka w zrodle: pojedynczy `Feature`, tak jak przy zeskanowanym obszarze. */
function chunkFeature(ring: number[][]) {
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } }
}

/** Policzone kawalki siedza w jednym zrodle jako kolekcja — po jednym prostokacie na kawalek. */
function chunkCollection(rings: number[][][]) {
  return { type: 'FeatureCollection', features: rings.map(chunkFeature) }
}

// Postep analizy: kawalek, ktory model liczy teraz. Bez tej ramki minuta pracy wyglada na
// zawieszona, bo pomaranczowe obrysy pojawiaja sie dopiero po kazdym kawalku.
it('frames the chunk under analysis from its own source, under the model outlines and the highlight', () => {
  render(<MapView analysingChunk={CHUNKS[0]} suspectedRoofs={[ROOF]} />)
  fire('style.load')

  expect(sources.map(([id]) => id)).toContain(CHUNK_CURRENT_SOURCE_ID)
  expect(sourceData(CHUNK_CURRENT_SOURCE_ID)).toEqual(chunkFeature(CHUNK_RINGS[0]))
  const ids = layerIds()
  // Nad budynkami (inaczej wypelnienie by ramke przykrylo), ale pod wynikiem modelu i pod wyborem.
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentFill)).toBeGreaterThan(ids.indexOf(LAYER_IDS.outline))
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentOutline)).toBeLessThan(ids.indexOf(SUSPECTED_LAYER_IDS.outline))
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentOutline)).toBeLessThan(ids.indexOf(LAYER_IDS.selectedFill))
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentFill)).toBeLessThan(ids.indexOf(CHUNK_LAYER_IDS.currentOutline))
})

it('frames a chunk that arrives after the style has loaded, still under the highlight', () => {
  const view = render(<MapView />)
  fire('style.load')
  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])

  view.rerender(<MapView analysingChunk={CHUNKS[0]} />)

  expect(sourceData(CHUNK_CURRENT_SOURCE_ID)).toEqual(chunkFeature(CHUNK_RINGS[0]))
  const ids = layerIds()
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentOutline)).toBeLessThan(ids.indexOf(LAYER_IDS.selectedFill))
})

// Kawalki ida jeden po drugim, wiec ramka przeskakuje co kilkanascie sekund. Usuwanie i dodawanie
// zrodla zabieraloby ze soba warstwy i mrugaloby ramka przy kazdym przeskoku.
it('moves the frame to the next chunk without duplicating the source or the layers', () => {
  const view = render(<MapView analysingChunk={CHUNKS[0]} />)
  fire('style.load')

  view.rerender(<MapView analysingChunk={CHUNKS[1]} />)

  expect(sourceData(CHUNK_CURRENT_SOURCE_ID)).toEqual(chunkFeature(CHUNK_RINGS[1]))
  expect(sources.filter(([id]) => id === CHUNK_CURRENT_SOURCE_ID)).toHaveLength(1)
  expect(layerIds().filter((id) => id === CHUNK_LAYER_IDS.currentOutline)).toHaveLength(1)
  expect(layerIds().filter((id) => id === CHUNK_LAYER_IDS.currentFill)).toHaveLength(1)
})

// To wypelnienie robi efekt przemiatania: zaznaczenie wypelnia sie od zachodu na wschod,
// czyli w kolejnosci, w ktorej plan oddal kawalki.
it('grows the analysed chunks one rectangle at a time', () => {
  const view = render(<MapView analysedChunks={[CHUNKS[0]]} />)
  fire('style.load')

  expect(sourceData(CHUNK_DONE_SOURCE_ID)).toEqual(chunkCollection([CHUNK_RINGS[0]]))
  expect(layerIds()).toContain(CHUNK_LAYER_IDS.doneFill)

  view.rerender(<MapView analysedChunks={[CHUNKS[0], CHUNKS[1]]} />)
  expect(sourceData(CHUNK_DONE_SOURCE_ID)).toEqual(chunkCollection([CHUNK_RINGS[0], CHUNK_RINGS[1]]))

  view.rerender(<MapView analysedChunks={CHUNKS} />)
  expect(sourceData(CHUNK_DONE_SOURCE_ID)).toEqual(chunkCollection(CHUNK_RINGS))
  // Jedno zrodlo i jedna warstwa przez caly przebieg, mimo trzech podmian danych.
  expect(sources.filter(([id]) => id === CHUNK_DONE_SOURCE_ID)).toHaveLength(1)
  expect(layerIds().filter((id) => id === CHUNK_LAYER_IDS.doneFill)).toHaveLength(1)
})

// Policzone leza pod aktualnym kawalkiem, zeby jego ramka zostala czytelna na wspolnej granicy
// dwoch sasiadujacych prostokatow.
it('keeps the analysed fill under the chunk that is being analysed', () => {
  render(<MapView analysingChunk={CHUNKS[1]} analysedChunks={[CHUNKS[0]]} />)
  fire('style.load')

  const ids = layerIds()
  expect(ids.indexOf(CHUNK_LAYER_IDS.doneFill)).toBeLessThan(ids.indexOf(CHUNK_LAYER_IDS.currentFill))
  expect(ids.indexOf(CHUNK_LAYER_IDS.doneFill)).toBeGreaterThan(ids.indexOf(LAYER_IDS.outline))
})

// Ta kolejnosc powstaje takze wtedy, gdy warstwy dokladaja sie po kolei w trakcie pracy:
// aktualny kawalek jest na mapie wczesniej niz pierwszy policzony.
it('keeps the analysed fill under the current chunk even when it arrives later', () => {
  const view = render(<MapView analysingChunk={CHUNKS[0]} />)
  fire('style.load')

  view.rerender(<MapView analysingChunk={CHUNKS[1]} analysedChunks={[CHUNKS[0]]} suspectedRoofs={[ROOF]} />)

  const ids = layerIds()
  expect(ids.indexOf(CHUNK_LAYER_IDS.doneFill)).toBeLessThan(ids.indexOf(CHUNK_LAYER_IDS.currentFill))
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentOutline)).toBeLessThan(ids.indexOf(SUSPECTED_LAYER_IDS.outline))
})

// Koniec analizy: nie ma „aktualnego" kawalka, a policzone przestaja byc informacja — zostaje
// sam wynik. Pusta lista znaczy tu to samo co `null`, inaczej niz przy wyniku modelu.
it('takes both progress layers off the map when the analysis is over', () => {
  const view = render(<MapView analysingChunk={CHUNKS[2]} analysedChunks={[CHUNKS[0], CHUNKS[1]]} />)
  fire('style.load')

  view.rerender(<MapView analysingChunk={null} analysedChunks={[]} />)

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])
  expect(layerIds()).toEqual(Object.values(LAYER_IDS))
})

it('takes the progress off the map when the props go back to null', () => {
  const view = render(<MapView analysingChunk={CHUNKS[0]} analysedChunks={[CHUNKS[0]]} />)
  fire('style.load')

  view.rerender(<MapView analysingChunk={null} analysedChunks={null} />)

  expect(sources.map(([id]) => id)).toEqual([SOURCE_ID])
  expect(layerIds()).toEqual(Object.values(LAYER_IDS))
})

// Blad kawalka: aktualnego juz nie ma, ale policzone zostaja — pokazuja, ile obszaru model
// obejrzal, zanim przestal odpowiadac.
it('keeps the analysed chunks after the current one disappears', () => {
  const view = render(<MapView analysingChunk={CHUNKS[1]} analysedChunks={[CHUNKS[0]]} />)
  fire('style.load')

  view.rerender(<MapView analysingChunk={null} analysedChunks={[CHUNKS[0]]} />)

  expect(layerIds()).not.toContain(CHUNK_LAYER_IDS.currentOutline)
  expect(layerIds()).not.toContain(CHUNK_LAYER_IDS.currentFill)
  expect(sources.map(([id]) => id)).not.toContain(CHUNK_CURRENT_SOURCE_ID)
  expect(layerIds()).toContain(CHUNK_LAYER_IDS.doneFill)
  expect(sourceData(CHUNK_DONE_SOURCE_ID)).toEqual(chunkCollection([CHUNK_RINGS[0]]))
})

// `setStyle` zabiera wszystko dodane recznie. Analiza trwa minute, wiec uzytkownik ma czas
// przelaczyc podklad w jej trakcie — postep musi wrocic razem z geometria i na to samo miejsce.
it('brings the analysis progress back after a basemap swap', () => {
  const view = render(
    <MapView analysingChunk={CHUNKS[1]} analysedChunks={[CHUNKS[0]]} suspectedRoofs={[ROOF]} basemap="standard" />,
  )
  fire('style.load')

  view.rerender(
    <MapView analysingChunk={CHUNKS[1]} analysedChunks={[CHUNKS[0]]} suspectedRoofs={[ROOF]} basemap="orthophoto" />,
  )
  expect(sources).toHaveLength(0)
  expect(addedLayers).toHaveLength(0)

  fire('style.load')

  expect(sourceData(CHUNK_CURRENT_SOURCE_ID)).toEqual(chunkFeature(CHUNK_RINGS[1]))
  expect(sourceData(CHUNK_DONE_SOURCE_ID)).toEqual(chunkCollection([CHUNK_RINGS[0]]))
  const ids = layerIds()
  expect(ids.indexOf(CHUNK_LAYER_IDS.doneFill)).toBeLessThan(ids.indexOf(CHUNK_LAYER_IDS.currentFill))
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentOutline)).toBeLessThan(ids.indexOf(SUSPECTED_LAYER_IDS.outline))
  expect(ids.indexOf(CHUNK_LAYER_IDS.currentOutline)).toBeLessThan(ids.indexOf(LAYER_IDS.selectedFill))
})

// Test-straznik, jak przy warstwie podejrzen: oba prostokaty przykrywaja fragmenty zaznaczenia,
// wiec klikalne przejmowalyby kazde klikniecie w budynek pod spodem.
it('never lets a click on the analysis progress pass as a click on a building', () => {
  const onSelect = vi.fn()
  render(<MapView analysingChunk={CHUNKS[0]} analysedChunks={[CHUNKS[1]]} onSelect={onSelect} />)
  fire('style.load')
  hits = [{ id: 42, layer: { id: LAYER_IDS.fill } }]
  fire('click')

  expect(queries[0][1]).toEqual({ layers: [LAYER_IDS.fill] })
  for (const id of Object.values(CHUNK_LAYER_IDS)) {
    expect(CLICKABLE_LAYER_IDS).not.toContain(id)
    expect(handlers.filter((entry) => entry.layer === id)).toHaveLength(0)
  }
  // Klik trafia w budynek pod spodem, a nie w prostokat postepu nad nim.
  expect(onSelect).toHaveBeenCalledWith(42)
})

// Postep jest dodatkiem do wyniku, nie jego zamiennikiem: prostokat zeskanowanego obszaru zostaje
// bez zmian, a obrysy modelu i kolory rejestru nie traca nic.
it('leaves the scanned rectangle and the registry colours untouched', () => {
  const view = render(<MapView scannedArea={AREA} suspectedRoofs={[ROOF]} />)
  fire('style.load')

  view.rerender(
    <MapView scannedArea={AREA} suspectedRoofs={[ROOF]} analysingChunk={CHUNKS[1]} analysedChunks={[CHUNKS[0]]} />,
  )

  expect(sourceData(SCAN_AREA_SOURCE_ID)).toMatchObject({ geometry: { coordinates: [AREA_RING] } })
  expect(layerIds()).toContain(SCAN_AREA_LAYER_IDS.outline)
  expect(sourceData(SUSPECTED_SOURCE_ID)).toMatchObject({ features: [{ geometry: ROOF_GEOMETRY }] })
  expect(paintOf(LAYER_IDS.fill, 'fill-color')).toEqual(fillColor(true))
})

it('ignores a basemap prop that is already applied', () => {
  const view = render(<MapView basemap="orthophoto" />)
  fire('style.load')

  view.rerender(<MapView basemap="orthophoto" />)
  expect(styleSwaps).toHaveLength(0)

  view.rerender(<MapView basemap="minimal" />)
  fire('style.load')
  view.rerender(<MapView basemap="minimal" />)

  expect(styleSwaps).toEqual([[BASEMAPS.minimal.style, { diff: false }]])
})
