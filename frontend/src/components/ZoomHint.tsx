import { POINT_MIN_ZOOM, POLYGON_MIN_ZOOM } from '../map/layers'

/**
 * Backend wysyla obrysy dopiero od POLYGON_MIN_ZOOM, a nizej same punkty zgloszonych budynkow.
 * Bez tego komunikatu pusta mapa na malym zoomie wyglada jak awaria.
 */
export function ZoomHint({ zoom }: { zoom: number }) {
  if (zoom >= POLYGON_MIN_ZOOM) return null

  const text =
    zoom < POINT_MIN_ZOOM
      ? 'Przybliż mapę, aby zobaczyć budynki.'
      : 'Widzisz punkty budynków zgłoszonych w rejestrze. Przybliż, aby zobaczyć obrysy dachów.'

  return (
    <p className="rounded-full border border-slate-700 bg-slate-900/85 px-3 py-1 text-xs text-slate-300 shadow backdrop-blur">
      {text}
    </p>
  )
}
