import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { TILES_URL } from '../api/client'
import { INITIAL_CENTER, INITIAL_ZOOM, basemapStyle } from './basemap'
import { CLICKABLE_LAYER_IDS, HIGHLIGHT_LAYER_IDS, LAYER_IDS, SOURCE_ID, SOURCE_MAX_ZOOM } from './layers'
import { MapView } from './MapView'

type MapEvent = { point: { x: number; y: number } }
type Handler = (event: MapEvent) => void
type Feature = { id: number | string; layer: { id: string } }
type AddedLayer = { id: string; type: string }

const constructed: unknown[] = []
const added: unknown[] = []
const removed = vi.fn()
const sources: Array<[string, unknown]> = []
const addedLayers: AddedLayer[] = []
const setFilters: Array<[string, unknown]> = []
const handlers: Array<{ type: string; layer?: string; handler: Handler }> = []
const queries: Array<[unknown, unknown]> = []
const canvasStyle = { cursor: '' }
/** Co ma zwrocic queryRenderedFeatures dla kolejnego klikniecia. */
let hits: Feature[] = []
const ZOOM = 15

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
    addSource(id: string, spec: unknown) {
      sources.push([id, spec])
    }
    addLayer(layer: AddedLayer) {
      addedLayers.push(layer)
    }
    getLayer(id: string) {
      return addedLayers.find((layer) => layer.id === id)
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

it('selects the building behind a listed point', () => {
  const onSelect = vi.fn()
  render(<MapView selectedId={null} onSelect={onSelect} />)
  fire('style.load')
  hits = [{ id: '7', layer: { id: LAYER_IDS.points } }]
  fire('click')

  expect(onSelect).toHaveBeenCalledWith(7)
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
