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
    <p className="rounded-card border border-hairline bg-surface px-3 py-1.5 text-xs text-ink-muted shadow-[0_1px_3px_rgba(5,28,44,0.08)]">
      {text}
    </p>
  )
}
