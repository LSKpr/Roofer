import type { Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl'
import { expect, it, vi } from 'vitest'
import type { Coordinates } from '../api/client'
import { LAYER_IDS, SELECTED_COLOR, SOURCE_ID } from './layers'
import type { ScreenPoint } from './rectangleDraw'
import {
  DRAW_LAYER_IDS,
  DRAW_SOURCE_ID,
  EMPTY_PREVIEW,
  MIN_DRAG_PIXELS,
  attachRectangleDraw,
  boundsFromCorners,
  drawOutlineLayer,
  isDegenerate,
  rectanglePolygon,
} from './rectangleDraw'

/** Skala trywialnego rzutu atrapy: piksel w prawo to wiekszy lng, piksel w dol to mniejszy lat. */
const SCALE = 100

type FakeHandler = { type: string; handler: (event: MapMouseEvent) => void }
type FakeLayer = { id: string; type: string }
type FakeSource = { data: unknown; setData: (data: unknown) => void }

// jsdom nie ma WebGL, wiec MapLibre tu nie wstanie. Atrapa zapisuje, co modul zrobil z mapa.
function createFakeMap() {
  const layers: FakeLayer[] = []
  const handlers: FakeHandler[] = []
  const sources = new Map<string, FakeSource>()
  const canvas = { style: { cursor: '' } }
  const gestures = { dragPan: true, doubleClickZoom: true, boxZoom: true }

  function gesture(name: keyof typeof gestures) {
    return {
      enable: () => {
        gestures[name] = true
      },
      disable: () => {
        gestures[name] = false
      },
    }
  }

  const fake = {
    on(type: string, handler: (event: MapMouseEvent) => void) {
      handlers.push({ type, handler })
    },
    off(type: string, handler: (event: MapMouseEvent) => void) {
      const index = handlers.findIndex((entry) => entry.type === type && entry.handler === handler)
      if (index >= 0) handlers.splice(index, 1)
    },
    addSource(id: string, spec: { data?: unknown }) {
      const source: FakeSource = {
        data: spec.data,
        setData(data: unknown) {
          source.data = data
        },
      }
      sources.set(id, source)
    },
    getSource(id: string) {
      return sources.get(id)
    },
    removeSource(id: string) {
      sources.delete(id)
    },
    addLayer(layer: FakeLayer) {
      layers.push(layer)
    },
    getLayer(id: string) {
      return layers.find((layer) => layer.id === id)
    },
    removeLayer(id: string) {
      const index = layers.findIndex((layer) => layer.id === id)
      if (index >= 0) layers.splice(index, 1)
    },
    getCanvas() {
      return canvas
    },
    dragPan: gesture('dragPan'),
    doubleClickZoom: gesture('doubleClickZoom'),
    boxZoom: gesture('boxZoom'),
    project(coordinates: Coordinates) {
      return { x: coordinates.lng * SCALE, y: -coordinates.lat * SCALE }
    },
    unproject(point: ScreenPoint) {
      return { lng: point.x / SCALE, lat: -point.y / SCALE }
    },
  }

  return {
    map: fake as unknown as MapLibreMap,
    layers,
    handlers,
    sources,
    canvas,
    gestures,
    fire(type: string, point: ScreenPoint) {
      const event = {
        point,
        lngLat: fake.unproject(point),
        preventDefault: () => undefined,
      } as unknown as MapMouseEvent
      for (const entry of handlers.filter((item) => item.type === type)) entry.handler(event)
    },
    preview() {
      return sources.get(DRAW_SOURCE_ID)?.data
    },
  }
}

type Fake = ReturnType<typeof createFakeMap>

function drag(fake: Fake, from: ScreenPoint, to: ScreenPoint) {
  fake.fire('mousedown', from)
  fake.fire('mousemove', to)
  fake.fire('mouseup', to)
}

const TOP_LEFT: ScreenPoint = { x: 100, y: 100 }
const TOP_RIGHT: ScreenPoint = { x: 200, y: 100 }
const BOTTOM_LEFT: ScreenPoint = { x: 100, y: 200 }
const BOTTOM_RIGHT: ScreenPoint = { x: 200, y: 200 }
/** Prostokat, ktory daje kazde z czterech przeciagniec miedzy naroznikami powyzej. */
const EXPECTED = { ne: { lng: 2, lat: -1 }, sw: { lng: 1, lat: -2 } }

it('normalises the corners whichever way the drag went', () => {
  const a = { lng: 21.1, lat: 52.3 }
  const b = { lng: 21.4, lat: 52.1 }
  const expected = { ne: { lng: 21.4, lat: 52.3 }, sw: { lng: 21.1, lat: 52.1 } }

  expect(boundsFromCorners(a, b)).toEqual(expected)
  expect(boundsFromCorners(b, a)).toEqual(expected)
  expect(boundsFromCorners({ lng: a.lng, lat: b.lat }, { lng: b.lng, lat: a.lat })).toEqual(expected)
  expect(boundsFromCorners({ lng: b.lng, lat: a.lat }, { lng: a.lng, lat: b.lat })).toEqual(expected)
})

it('closes the polygon ring and keeps the lng, lat order', () => {
  const ring = rectanglePolygon(EXPECTED).geometry.coordinates[0]

  expect(ring).toHaveLength(5)
  expect(ring[0]).toEqual(ring[4])
  expect(ring).toEqual([
    [1, -2],
    [2, -2],
    [2, -1],
    [1, -1],
    [1, -2],
  ])
})

it('rejects only drags shorter than the pixel threshold', () => {
  expect(isDegenerate({ x: 10, y: 10 }, { x: 10, y: 10 })).toBe(true)
  expect(isDegenerate({ x: 10, y: 10 }, { x: 12, y: 12 })).toBe(true)
  expect(isDegenerate({ x: 10, y: 10 }, { x: 10 + MIN_DRAG_PIXELS, y: 10 })).toBe(false)
  expect(isDegenerate({ x: 10, y: 10 }, { x: 40, y: 40 })).toBe(false)
  // Prog jest parametrem, zeby nie trzeba bylo zgadywac go w wywolujacym.
  expect(isDegenerate({ x: 10, y: 10 }, { x: 20, y: 10 }, 50)).toBe(true)
})

it('uses its own ids, so it cannot collide with the building layers', () => {
  const ids = Object.values(DRAW_LAYER_IDS)

  expect(DRAW_SOURCE_ID).not.toBe(SOURCE_ID)
  for (const id of ids) expect(Object.values(LAYER_IDS)).not.toContain(id)
  expect(new Set(ids).size).toBe(ids.length)
})

it('draws the selection with the accent colour and a dashed outline', () => {
  expect(drawOutlineLayer.paint?.['line-color']).toBe(SELECTED_COLOR)
  expect(drawOutlineLayer.paint?.['line-dasharray']).toEqual([2, 2])
})

it('disables panning and sets the crosshair cursor on start', () => {
  const fake = createFakeMap()
  const draw = attachRectangleDraw(fake.map, { onComplete: vi.fn() })

  expect(fake.layers).toHaveLength(0)
  draw.start()

  expect(draw.active).toBe(true)
  expect(fake.gestures).toEqual({ dragPan: false, doubleClickZoom: false, boxZoom: false })
  expect(fake.canvas.style.cursor).toBe('crosshair')
  expect(fake.sources.has(DRAW_SOURCE_ID)).toBe(true)
  expect(fake.layers.map((layer) => layer.id)).toEqual([DRAW_LAYER_IDS.fill, DRAW_LAYER_IDS.outline])
})

it('reports the same bounds for all four drag directions', () => {
  const drags: Array<[ScreenPoint, ScreenPoint]> = [
    [TOP_LEFT, BOTTOM_RIGHT],
    [BOTTOM_RIGHT, TOP_LEFT],
    [TOP_RIGHT, BOTTOM_LEFT],
    [BOTTOM_LEFT, TOP_RIGHT],
  ]

  for (const [from, to] of drags) {
    const fake = createFakeMap()
    const onComplete = vi.fn()
    const draw = attachRectangleDraw(fake.map, { onComplete })
    draw.start()
    drag(fake, from, to)

    expect(onComplete).toHaveBeenCalledTimes(1)
    expect(onComplete).toHaveBeenCalledWith(EXPECTED)
    draw.destroy()
  }
})

it('shows the rectangle while dragging', () => {
  const fake = createFakeMap()
  const draw = attachRectangleDraw(fake.map, { onComplete: vi.fn() })
  draw.start()

  expect(fake.preview()).toEqual(EMPTY_PREVIEW)
  fake.fire('mousedown', TOP_LEFT)
  fake.fire('mousemove', BOTTOM_RIGHT)

  expect(fake.preview()).toEqual(rectanglePolygon(EXPECTED))
})

it('restores the map and clears the preview after one selection', () => {
  const fake = createFakeMap()
  const onComplete = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete })
  draw.start()
  drag(fake, TOP_LEFT, BOTTOM_RIGHT)

  expect(draw.active).toBe(false)
  expect(fake.gestures).toEqual({ dragPan: true, doubleClickZoom: true, boxZoom: true })
  expect(fake.canvas.style.cursor).toBe('')
  expect(fake.preview()).toEqual(EMPTY_PREVIEW)
  // Zaznaczenie jest jednorazowe: po skanie nasluchy nie wisza na mapie.
  expect(fake.handlers).toHaveLength(0)
  drag(fake, TOP_LEFT, BOTTOM_RIGHT)
  expect(onComplete).toHaveBeenCalledTimes(1)
})

it('can be started again without duplicating the source or the layers', () => {
  const fake = createFakeMap()
  const onComplete = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete })
  draw.start()
  drag(fake, TOP_LEFT, BOTTOM_RIGHT)
  draw.start()
  drag(fake, BOTTOM_RIGHT, TOP_LEFT)

  expect(onComplete).toHaveBeenCalledTimes(2)
  expect(fake.layers).toHaveLength(2)
  expect(fake.sources.size).toBe(1)
})

it('treats a click without a drag as a cancellation', () => {
  const fake = createFakeMap()
  const onComplete = vi.fn()
  const onCancel = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete, onCancel })
  draw.start()
  drag(fake, TOP_LEFT, { x: TOP_LEFT.x + 2, y: TOP_LEFT.y + 2 })

  expect(onComplete).not.toHaveBeenCalled()
  expect(onCancel).toHaveBeenCalledTimes(1)
  expect(draw.active).toBe(false)
  expect(fake.canvas.style.cursor).toBe('')
  expect(fake.gestures.dragPan).toBe(true)
})

it('ignores a mouseup that no mousedown started', () => {
  const fake = createFakeMap()
  const onComplete = vi.fn()
  const onCancel = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete, onCancel })
  draw.start()
  fake.fire('mouseup', BOTTOM_RIGHT)

  expect(onComplete).not.toHaveBeenCalled()
  expect(onCancel).not.toHaveBeenCalled()
  expect(draw.active).toBe(true)
})

it('cancels the drawing on Escape', () => {
  const fake = createFakeMap()
  const onComplete = vi.fn()
  const onCancel = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete, onCancel })
  draw.start()
  fake.fire('mousedown', TOP_LEFT)
  fake.fire('mousemove', BOTTOM_RIGHT)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

  expect(onCancel).toHaveBeenCalledTimes(1)
  expect(draw.active).toBe(false)
  expect(fake.preview()).toEqual(EMPTY_PREVIEW)
  expect(fake.canvas.style.cursor).toBe('')
  expect(fake.gestures).toEqual({ dragPan: true, doubleClickZoom: true, boxZoom: true })
  // Przerwane zaznaczenie nie moze dokonczyc sie samo przy puszczeniu przycisku.
  fake.fire('mouseup', BOTTOM_RIGHT)
  expect(onComplete).not.toHaveBeenCalled()
})

it('ignores keys other than Escape', () => {
  const fake = createFakeMap()
  const onCancel = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete: vi.fn(), onCancel })
  draw.start()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))

  expect(onCancel).not.toHaveBeenCalled()
  expect(draw.active).toBe(true)
  draw.destroy()
})

it('cancels on demand and stays quiet when nothing is being drawn', () => {
  const fake = createFakeMap()
  const onCancel = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete: vi.fn(), onCancel })
  draw.cancel()

  expect(onCancel).not.toHaveBeenCalled()

  draw.start()
  draw.cancel()

  expect(onCancel).toHaveBeenCalledTimes(1)
  expect(draw.active).toBe(false)
  draw.cancel()
  expect(onCancel).toHaveBeenCalledTimes(1)
})

it('removes the layers, the source and the listeners on destroy', () => {
  const fake = createFakeMap()
  const onComplete = vi.fn()
  const draw = attachRectangleDraw(fake.map, { onComplete })
  draw.start()
  fake.fire('mousedown', TOP_LEFT)
  draw.destroy()

  expect(fake.layers).toHaveLength(0)
  expect(fake.sources.size).toBe(0)
  expect(fake.handlers).toHaveLength(0)
  expect(draw.active).toBe(false)
  // Po zniszczeniu Escape ani przeciagniecie nie maja do czego wrocic.
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  draw.start()
  expect(draw.active).toBe(false)
  expect(onComplete).not.toHaveBeenCalled()
})

it('survives a second destroy and a destroy after the map is gone', () => {
  const fake = createFakeMap()
  const draw = attachRectangleDraw(fake.map, { onComplete: vi.fn() })
  draw.start()
  draw.destroy()

  expect(() => draw.destroy()).not.toThrow()

  // Po `map.remove()` styl jest zburzony: nawet pytanie o warstwe rzuca.
  const dead = createFakeMap()
  const second = attachRectangleDraw(dead.map, { onComplete: vi.fn() })
  second.start()
  const broken = dead.map as unknown as { getLayer: () => never; getSource: () => never }
  broken.getLayer = () => {
    throw new Error('map is removed')
  }
  broken.getSource = () => {
    throw new Error('map is removed')
  }

  expect(() => second.destroy()).not.toThrow()
})
