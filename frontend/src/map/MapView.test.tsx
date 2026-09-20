import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { Bounds } from '../api/client'
import { TILES_URL } from '../api/client'
import { BASEMAPS, DEFAULT_BASEMAP, INITIAL_CENTER, INITIAL_ZOOM, basemapStyle } from './basemap'
import {
  CLICKABLE_LAYER_IDS,
  HIGHLIGHT_LAYER_IDS,
  LAYER_IDS,
  SCAN_AREA_LAYER_IDS,
  SCAN_AREA_SOURCE_ID,
  SOURCE_ID,
  SOURCE_MAX_ZOOM,
} from './layers'
import { MapView } from './MapView'

type MapEvent = { point: { x: number; y: number } }
type Handler = (event: MapEvent) => void
type Feature = { id: number | string; layer: { id: string } }
type AddedLayer = { id: string; type: string }
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
    addLayer(layer: AddedLayer) {
      addedLayers.push(layer)
    }
    getLayer(id: string) {
      return addedLayers.find((layer) => layer.id === id)
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
