import { Map as MapLibreMap, NavigationControl, ScaleControl } from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import { INITIAL_CENTER, INITIAL_ZOOM, MAX_ZOOM, MIN_ZOOM, basemapStyle } from './basemap'
import {
  CLICKABLE_LAYER_IDS,
  HIGHLIGHT_LAYER_IDS,
  MAP_LAYERS,
  SOURCE_ID,
  buildingsSource,
  selectedFilter,
} from './layers'

export type MapViewProps = {
  /** Identyfikator budynku do podswietlenia; `null` znaczy „nic nie wybrano". */
  selectedId?: number | null
  onSelect?: (id: number | null) => void
  /** Aktualny zoom po kazdym przesunieciu — na komunikat „przybliz, aby zobaczyc obrysy". */
  onZoomChange?: (zoom: number) => void
}

/** Filtr ustawiamy tylko na warstwach, ktore juz istnieja — powstaja dopiero po `style.load`. */
function applyHighlight(instance: MapLibreMap, id: number | null) {
  const filter = selectedFilter(id)
  for (const layerId of HIGHLIGHT_LAYER_IDS) {
    if (instance.getLayer(layerId)) instance.setFilter(layerId, filter)
  }
}

export function MapView({ selectedId = null, onSelect, onZoomChange }: MapViewProps) {
  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<MapLibreMap | null>(null)
  // Mapa powstaje raz, wiec handlery musza czytac propsy z refow. Inaczej zamknelyby sie
  // na wartosciach z pierwszego renderu albo wymusilyby przebudowe mapy przy kazdym renderze.
  const selectRef = useRef(onSelect)
  const zoomRef = useRef(onZoomChange)
  const selectedRef = useRef(selectedId)
  const styleReady = useRef(false)

  useEffect(() => {
    selectRef.current = onSelect
    zoomRef.current = onZoomChange
    selectedRef.current = selectedId
  })

  useEffect(() => {
    if (!container.current || map.current) return
    const instance = new MapLibreMap({
      container: container.current,
      style: basemapStyle,
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
      instance.addSource(SOURCE_ID, buildingsSource)
      for (const layer of MAP_LAYERS) instance.addLayer(layer)
      // Wybor moze pochodzic z czasu przed zaladowaniem stylu (np. z adresu URL).
      applyHighlight(instance, selectedRef.current)

      for (const layerId of CLICKABLE_LAYER_IDS) {
        instance.on('mouseenter', layerId, () => {
          instance.getCanvas().style.cursor = 'pointer'
        })
        instance.on('mouseleave', layerId, () => {
          instance.getCanvas().style.cursor = ''
        })
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

    map.current = instance
    return () => {
      instance.remove()
      styleReady.current = false
      map.current = null
    }
  }, [])

  // Przed `style.load` nie ma czego filtrowac — wybor z tego czasu nadrabia sam handler stylu.
  useEffect(() => {
    const instance = map.current
    if (!instance || !styleReady.current) return
    applyHighlight(instance, selectedId)
  }, [selectedId])

  return <div ref={container} data-testid="map" className="h-full w-full" />
}
