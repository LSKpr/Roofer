import { Map as MapLibreMap, NavigationControl, ScaleControl } from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import { INITIAL_CENTER, INITIAL_ZOOM, MAX_ZOOM, MIN_ZOOM, basemapStyle } from './basemap'

export function MapView() {
  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<MapLibreMap | null>(null)

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
    instance.addControl(new NavigationControl(), 'top-right')
    instance.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')
    map.current = instance
    return () => {
      instance.remove()
      map.current = null
    }
  }, [])

  return <div ref={container} data-testid="map" className="h-full w-full" />
}
