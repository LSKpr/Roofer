import type {
  FillLayerSpecification,
  GeoJSONSource,
  LineLayerSpecification,
  Map as MapLibreMap,
  MapMouseEvent,
  SourceSpecification,
} from 'maplibre-gl'
import type { Bounds, Coordinates } from '../api/client'
import { SELECTED_COLOR } from './layers'

/**
 * Wlasne identyfikatory, rozlaczne z `LAYER_IDS` z layers.ts. Podglad zaznaczenia nie jest dana
 * z kafla, wiec nie moze wpasc w te same nazwy ani w filtry warstw budynkow.
 */
export const DRAW_SOURCE_ID = 'roofer-draw'

export const DRAW_LAYER_IDS = {
  fill: 'roofer-draw-fill',
  outline: 'roofer-draw-outline',
}

/** Punkt na ekranie w pikselach — tyle, ile daje `MapMouseEvent.point`. */
export type ScreenPoint = { x: number; y: number }

/**
 * `@types/geojson` przychodzi z MapLibre, ale tylko jako jej wlasna zaleznosc: pnpm nie stawia go
 * w naszym `node_modules`, a `tsconfig.app.json` ma `types: ["vite/client"]`, wiec ani globalna
 * przestrzen `GeoJSON`, ani `import from 'geojson'` sie tu nie rozwiazuja. Nowej zaleznosci nie
 * dodajemy, wiec opisujemy dokladnie tyle geometrii, ile ten modul naprawde produkuje.
 */
export type Position = [number, number]
export type PolygonGeometry = { type: 'Polygon'; coordinates: Position[][] }
export type RectangleFeature = {
  type: 'Feature'
  properties: Record<string, never>
  geometry: PolygonGeometry
}
export type EmptyCollection = { type: 'FeatureCollection'; features: [] }

/**
 * Prog odrzucenia zaznaczenia liczymy w pikselach ekranu, nie w stopniach: ten sam ruch myszka
 * ma znaczyc to samo w kazdym zoomie, a przy zoomie 8 piec pikseli to kilkaset metrow.
 * Piec pikseli to tyle, ile kursor „ucieka" przy zwyklym kliknieciu (drgniecie reki przy
 * wcisnietym przycisku) — ponizej tego uznajemy, ze uzytkownik kliknal, a nie rysowal ramke.
 */
export const MIN_DRAG_PIXELS = 5

/** Pusty podglad: zrodlo musi istniec caly czas, bo warstwy nie moga wisiec w powietrzu. */
export const EMPTY_PREVIEW: EmptyCollection = { type: 'FeatureCollection', features: [] }

type PreviewData = RectangleFeature | EmptyCollection

export const drawSource: SourceSpecification = { type: 'geojson', data: EMPTY_PREVIEW }

/** Wypelnienie tylko sygnalizuje obszar — dane pod ramka musza zostac czytelne. */
export const drawFillLayer: FillLayerSpecification = {
  id: DRAW_LAYER_IDS.fill,
  type: 'fill',
  source: DRAW_SOURCE_ID,
  paint: {
    'fill-color': SELECTED_COLOR,
    'fill-opacity': 0.12,
  },
}

/** Linia przerywana czyta sie jako „zaznaczenie w toku", a ciagla wygladalaby jak obrys danych. */
export const drawOutlineLayer: LineLayerSpecification = {
  id: DRAW_LAYER_IDS.outline,
  type: 'line',
  source: DRAW_SOURCE_ID,
  paint: {
    'line-color': SELECTED_COLOR,
    'line-width': 2,
    'line-dasharray': [2, 2],
  },
}

/** Kolejnosc dodawania: wypelnienie pod obrysem. */
export const DRAW_LAYERS = [drawFillLayer, drawOutlineLayer]

/**
 * Kierunek przeciagniecia jest informacja o rece uzytkownika, nie o obszarze, wiec znika tutaj:
 * `ne` to zawsze maksima, `sw` minima. Backend (`POST /api/area/scan`) dostaje jeden kanoniczny
 * ksztalt niezaleznie od tego, z ktorego naroznika zaczeto.
 */
export function boundsFromCorners(a: Coordinates, b: Coordinates): Bounds {
  return {
    ne: { lng: Math.max(a.lng, b.lng), lat: Math.max(a.lat, b.lat) },
    sw: { lng: Math.min(a.lng, b.lng), lat: Math.min(a.lat, b.lat) },
  }
}

/**
 * Pierscien domykamy recznie (pierwszy punkt rowny ostatniemu, piec wierzcholkow), bo GeoJSON
 * tego wymaga, a MapLibre po cichu nie rysuje niedomknietych wielokatow.
 * Obieg SW → SE → NE → NW jest przeciwny do ruchu wskazowek zegara, jak zaleca RFC 7946.
 */
export function rectanglePolygon(bounds: Bounds): RectangleFeature {
  const { ne, sw } = bounds
  return {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [sw.lng, sw.lat],
          [ne.lng, sw.lat],
          [ne.lng, ne.lat],
          [sw.lng, ne.lat],
          [sw.lng, sw.lat],
        ],
      ],
    },
  }
}

/** Zaznaczenie krotsze niz `minPixels` po przekatnej to klik, nie ramka — patrz MIN_DRAG_PIXELS. */
export function isDegenerate(a: ScreenPoint, b: ScreenPoint, minPixels: number = MIN_DRAG_PIXELS): boolean {
  return Math.hypot(b.x - a.x, b.y - a.y) < minPixels
}

export type RectangleDrawOptions = {
  onComplete: (bounds: Bounds) => void
  /** Wolane przy Escape, przy `cancel()` i przy kliknieciu bez przeciagniecia. */
  onCancel?: () => void
}

export type RectangleDraw = {
  start(): void
  cancel(): void
  destroy(): void
  readonly active: boolean
}

/**
 * Sprzatanie musi dzialac takze po `map.remove()`, a wtedy styl jest juz zburzony i nawet samo
 * pytanie o warstwe potrafi rzucic. Bledu na tym etapie nie ma jak naprawic ani po co pokazywac.
 */
function silently(work: () => void): void {
  try {
    work()
  } catch {
    return
  }
}

/**
 * Przeciagniecie myszka to w MapLibre domyslnie przesuniecie mapy, wiec bez wylaczenia `dragPan`
 * ramka nie da sie narysowac — mapa ucieklaby pod kursorem. `boxZoom` (shift + przeciagniecie)
 * i `doubleClickZoom` wchodza w te same zdarzenia, wiec na czas rysowania tez ida w dol.
 * Uchwyty sprawdzamy przez `?.`, bo nie kazda wersja mapy musi je miec.
 */
function setGestures(map: MapLibreMap, enabled: boolean): void {
  if (enabled) {
    map.dragPan?.enable()
    map.doubleClickZoom?.enable()
    map.boxZoom?.enable()
    return
  }
  map.dragPan?.disable()
  map.doubleClickZoom?.disable()
  map.boxZoom?.disable()
}

export function attachRectangleDraw(map: MapLibreMap, options: RectangleDrawOptions): RectangleDraw {
  let active = false
  let destroyed = false
  let firstCorner: Coordinates | null = null
  let firstPoint: ScreenPoint | null = null
  let previousCursor = ''

  function setPreview(data: PreviewData): void {
    const source = map.getSource<GeoJSONSource>(DRAW_SOURCE_ID)
    if (source) source.setData(data)
  }

  /**
   * Zrodlo i warstwy dokladamy dopiero przy pierwszym rysowaniu: przy podlaczeniu styl moze
   * jeszcze nie byc zaladowany. `setStyle` (zmiana podkladu) zabiera warstwy dodane recznie,
   * wiec dokladanie musi byc odporne na powtorzenie — tak samo jak w MapView.
   */
  function ensurePreview(): void {
    if (!map.getSource(DRAW_SOURCE_ID)) map.addSource(DRAW_SOURCE_ID, drawSource)
    for (const layer of DRAW_LAYERS) {
      if (!map.getLayer(layer.id)) map.addLayer(layer)
    }
  }

  function handleDown(event: MapMouseEvent): void {
    firstCorner = { lng: event.lngLat.lng, lat: event.lngLat.lat }
    firstPoint = { x: event.point.x, y: event.point.y }
    // Domyslne gesty sa juz wylaczone, ale `preventDefault` zatrzymuje takze obrot mapy
    // prawym przyciskiem, ktorego nie ruszamy.
    event.preventDefault()
  }

  function handleMove(event: MapMouseEvent): void {
    if (!firstCorner) return
    setPreview(rectanglePolygon(boundsFromCorners(firstCorner, event.lngLat)))
  }

  function handleUp(event: MapMouseEvent): void {
    if (!firstCorner || !firstPoint) return
    const bounds = boundsFromCorners(firstCorner, event.lngLat)
    const degenerate = isDegenerate(firstPoint, event.point)
    // Tryb gasnie przed wywolaniem zwrotnym: zaznaczenie jest jednorazowe, a odbiorca moze
    // w reakcji wlaczyc rysowanie od nowa.
    stop()
    if (degenerate) {
      options.onCancel?.()
      return
    }
    options.onComplete(bounds)
  }

  /** Canvas mapy nie musi miec fokusu, wiec Escape lapiemy na oknie, nie na mapie. */
  function handleKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return
    cancel()
  }

  function detach(): void {
    map.off('mousedown', handleDown)
    map.off('mousemove', handleMove)
    map.off('mouseup', handleUp)
    window.removeEventListener('keydown', handleKey)
  }

  function stop(): void {
    active = false
    firstCorner = null
    firstPoint = null
    detach()
    silently(() => setPreview(EMPTY_PREVIEW))
    silently(() => {
      map.getCanvas().style.cursor = previousCursor
    })
    silently(() => setGestures(map, true))
  }

  function start(): void {
    if (destroyed || active) return
    active = true
    ensurePreview()
    const canvas = map.getCanvas()
    previousCursor = canvas.style.cursor
    canvas.style.cursor = 'crosshair'
    setGestures(map, false)
    map.on('mousedown', handleDown)
    map.on('mousemove', handleMove)
    map.on('mouseup', handleUp)
    window.addEventListener('keydown', handleKey)
  }

  function cancel(): void {
    if (!active) return
    stop()
    options.onCancel?.()
  }

  function destroy(): void {
    if (destroyed) return
    destroyed = true
    if (active) stop()
    else detach()
    silently(() => {
      // Najpierw warstwy, potem zrodlo: MapLibre nie usunie zrodla, z ktorego ktos jeszcze czyta.
      for (const layer of DRAW_LAYERS) {
        if (map.getLayer(layer.id)) map.removeLayer(layer.id)
      }
      if (map.getSource(DRAW_SOURCE_ID)) map.removeSource(DRAW_SOURCE_ID)
    })
  }

  return {
    start,
    cancel,
    destroy,
    get active() {
      return active
    },
  }
}
