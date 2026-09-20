import { Map as MapLibreMap, NavigationControl, ScaleControl } from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import type { Bounds } from '../api/client'
import { attachRectangleDraw, type RectangleDraw } from './rectangleDraw'
import type { BasemapId } from './basemap'
import { BASEMAPS, DEFAULT_BASEMAP, INITIAL_CENTER, INITIAL_ZOOM, MAX_ZOOM, MIN_ZOOM } from './basemap'
import {
  CLICKABLE_LAYER_IDS,
  HIGHLIGHT_LAYER_IDS,
  MAP_LAYERS,
  SOURCE_ID,
  buildingsSource,
  selectedFilter,
} from './layers'

/**
 * Cel kamery. Wyszukiwarka oddaje albo prostokat miejscowosci, albo sam punkt (adres, przysiolek),
 * wiec mapa musi umiec jedno i drugie. Kolejnosc w `bounds` to [zachod, poludnie, wschod, polnoc].
 */
export type MapFocus =
  | { kind: 'bounds'; bounds: [number, number, number, number] }
  | { kind: 'point'; center: [number, number]; zoom: number }

export type MapViewProps = {
  /** Identyfikator budynku do podswietlenia; `null` znaczy „nic nie wybrano". */
  selectedId?: number | null
  onSelect?: (id: number | null) => void
  /** Aktualny zoom po kazdym przesunieciu — na komunikat „przybliz, aby zobaczyc obrysy". */
  onZoomChange?: (zoom: number) => void
  /** Podklad mapy. Zmiana podmienia sam styl, mapa i warstwy budynkow zostaja. */
  basemap?: BasemapId
  /** Kazdy nowy obiekt przesuwa kamere; `null` nie robi nic. */
  focus?: MapFocus | null
  /** Tryb rysowania prostokata do skanu. Wylacza przeciaganie mapy, dopoki trwa. */
  drawing?: boolean
  onDrawComplete?: (bounds: Bounds) => void
  onDrawCancel?: () => void
}

/** Filtr ustawiamy tylko na warstwach, ktore juz istnieja — powstaja dopiero po `style.load`. */
function applyHighlight(instance: MapLibreMap, id: number | null) {
  const filter = selectedFilter(id)
  for (const layerId of HIGHLIGHT_LAYER_IDS) {
    if (instance.getLayer(layerId)) instance.setFilter(layerId, filter)
  }
}

/**
 * `style.load` leci po kazdym `setStyle`, a MapLibre razem ze starym stylem usuwa zrodla i warstwy
 * dodane recznie. Dlatego dokladanie musi byc odporne na powtorzenie: sprawdzamy, czego brakuje,
 * zamiast zakladac czysta mape.
 */
function addBuildingLayers(instance: MapLibreMap) {
  if (!instance.getSource(SOURCE_ID)) instance.addSource(SOURCE_ID, buildingsSource)
  for (const layer of MAP_LAYERS) {
    if (!instance.getLayer(layer.id)) instance.addLayer(layer)
  }
}

export function MapView({
  selectedId = null,
  onSelect,
  onZoomChange,
  basemap = DEFAULT_BASEMAP,
  focus = null,
  drawing = false,
  onDrawComplete,
  onDrawCancel,
}: MapViewProps) {
  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<MapLibreMap | null>(null)
  // Mapa powstaje raz, wiec handlery musza czytac propsy z refow. Inaczej zamknelyby sie
  // na wartosciach z pierwszego renderu albo wymusilyby przebudowe mapy przy kazdym renderze.
  const selectRef = useRef(onSelect)
  const zoomRef = useRef(onZoomChange)
  const selectedRef = useRef(selectedId)
  const drawCompleteRef = useRef(onDrawComplete)
  const drawCancelRef = useRef(onDrawCancel)
  const draw = useRef<RectangleDraw | null>(null)
  const styleReady = useRef(false)
  // Styl, ktory mapa juz dostala. Pierwszy dostaje przez konstruktor, wiec `setStyle` na starcie
  // byloby drugim, niepotrzebnym zaladowaniem tych samych kafli.
  const appliedBasemap = useRef(basemap)
  const hoverBound = useRef(false)

  useEffect(() => {
    selectRef.current = onSelect
    zoomRef.current = onZoomChange
    selectedRef.current = selectedId
    drawCompleteRef.current = onDrawComplete
    drawCancelRef.current = onDrawCancel
  })

  useEffect(() => {
    if (!container.current || map.current) return
    const instance = new MapLibreMap({
      container: container.current,
      style: BASEMAPS[appliedBasemap.current].style,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
    })
    // Oba w prawym dolnym rogu: gorny prawy zajmuje karta budynku, a dolny lewy legenda.
    instance.addControl(new NavigationControl(), 'bottom-right')
    instance.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-right')

    instance.on('style.load', () => {
      styleReady.current = true
      addBuildingLayers(instance)
      // Wybor moze pochodzic z czasu przed zaladowaniem stylu (np. z adresu URL) albo przetrwac
      // zmiane podkladu, ktora zabrala warstwy podswietlenia razem ze starym stylem.
      applyHighlight(instance, selectedRef.current)

      // Handlery kursora zostaja przy mapie, nie przy stylu, wiec rejestrujemy je tylko raz —
      // po drugim `style.load` mielibysmy inaczej dwa zestawy tych samych nasluchow.
      if (!hoverBound.current) {
        hoverBound.current = true
        for (const layerId of CLICKABLE_LAYER_IDS) {
          instance.on('mouseenter', layerId, () => {
            instance.getCanvas().style.cursor = 'pointer'
          })
          instance.on('mouseleave', layerId, () => {
            instance.getCanvas().style.cursor = ''
          })
        }
      }

      zoomRef.current?.(instance.getZoom())
    })

    // Jeden handler na cala mape zamiast osobnych na warstwach: klik w obrys i klik w pustke
    // to ta sama decyzja, a przy dwoch handlerach kazdy klik w budynek wolalby onSelect dwa razy.
    instance.on('click', (event) => {
      const layers = CLICKABLE_LAYER_IDS.filter((layerId) => instance.getLayer(layerId))
      const features = layers.length > 0 ? instance.queryRenderedFeatures(event.point, { layers }) : []
      const hit = features.find((feature) => feature.id !== undefined && feature.id !== null)
      selectRef.current?.(hit ? Number(hit.id) : null)
    })

    instance.on('zoomend', () => {
      zoomRef.current?.(instance.getZoom())
    })

    // Rysowanie dokłada swoje warstwy dopiero przy `start()`, wiec wolno je doczepic przed
    // zaladowaniem stylu.
    draw.current = attachRectangleDraw(instance, {
      onComplete: (bounds) => drawCompleteRef.current?.(bounds),
      onCancel: () => drawCancelRef.current?.(),
    })

    map.current = instance
    return () => {
      draw.current?.destroy()
      draw.current = null
      instance.remove()
      styleReady.current = false
      hoverBound.current = false
      map.current = null
    }
  }, [])

  /**
   * Podmieniamy sam styl, zeby nie tracic instancji mapy, kamery ani nasluchow. `diff: false`
   * jest tu konieczne: przy domyslnym diffie MapLibre porownuje nowy styl z aktualnym, w ktorym
   * siedza nasze recznie dodane warstwy budynkow — usunalby je jako „nadmiarowe" i nie wyslalby
   * `style.load`, wiec nie mielibysmy momentu, w ktorym je odtworzyc.
   */
  useEffect(() => {
    const instance = map.current
    if (!instance || appliedBasemap.current === basemap) return
    appliedBasemap.current = basemap
    styleReady.current = false
    instance.setStyle(BASEMAPS[basemap].style, { diff: false })
  }, [basemap])

  /**
   * `maxZoom` przy prostokacie miejscowosci: bez tego `fitBounds` na malej wsi wjezdza na zoom 18,
   * gdzie widac trzy budynki. `POLYGON_MIN_ZOOM` z layers.ts to progi obrysow, wiec dolny limit
   * trzyma nas w zakresie, w ktorym mapa cokolwiek pokazuje.
   */
  useEffect(() => {
    const instance = map.current
    if (!instance || !focus) return
    if (focus.kind === 'bounds') {
      const [west, south, east, north] = focus.bounds
      instance.fitBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: 48, maxZoom: 17, duration: 600 },
      )
      return
    }
    instance.flyTo({ center: focus.center, zoom: focus.zoom, duration: 600 })
  }, [focus])

  /** Tryb rysowania wlacza rodzic propsem; modul sam sie wylacza po zakonczeniu ramki. */
  useEffect(() => {
    const handle = draw.current
    if (!handle) return
    if (drawing && !handle.active) handle.start()
    if (!drawing && handle.active) handle.cancel()
  }, [drawing])

  // Przed `style.load` nie ma czego filtrowac — wybor z tego czasu nadrabia sam handler stylu.
  useEffect(() => {
    const instance = map.current
    if (!instance || !styleReady.current) return
    applyHighlight(instance, selectedId)
  }, [selectedId])

  return <div ref={container} data-testid="map" className="h-full w-full" />
}
