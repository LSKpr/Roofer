/**
 * Kolory statusow trzymamy w stalych, zeby probka w legendzie nie rozjechala sie z mapa.
 *
 * TODO: po scaleniu wziac te kolory z STATUS_COLORS w src/map/layers.ts — teraz sa swiadomie
 * zdublowane, bo legenda i warstwy mapy powstaja rownolegle.
 */
export const LISTED_COLOR = '#EF4444'
export const NOT_LISTED_COLOR = '#64748B'

type LegendProps = { className?: string }

export function Legend({ className }: LegendProps) {
  return (
    <section
      aria-label="Legenda mapy"
      className={`w-72 rounded-lg border border-slate-700 bg-slate-900/80 p-3 text-slate-100 shadow-lg backdrop-blur ${className ?? ''}`}
    >
      <h2 className="text-sm font-semibold">Legenda</h2>
      <ul className="mt-2 space-y-1.5 text-xs">
        <li className="flex items-center gap-2">
          <span
            data-testid="legend-swatch"
            className="inline-block h-3 w-3 shrink-0 rounded-sm border border-slate-600"
            style={{ backgroundColor: LISTED_COLOR }}
          />
          Zgłoszony w rejestrze GeoAzbest
        </li>
        <li className="flex items-center gap-2">
          <span
            data-testid="legend-swatch"
            className="inline-block h-3 w-3 shrink-0 rounded-sm border border-slate-600"
            style={{ backgroundColor: NOT_LISTED_COLOR }}
          />
          Niezgłoszony
        </li>
      </ul>
      <p className="mt-3 text-xs text-slate-400">
        Rejestr jest niekompletny: brak budynku w rejestrze nie jest dowodem, że dach jest czysty — znaczy tylko,
        że nikt go nie zgłosił.
      </p>
      <p className="mt-2 text-xs text-slate-400">
        Po oddaleniu mapy widoczne są tylko zgłoszone budynki, i to jako punkty. Obrysy pojawiają się od zoomu 14,
        punkty od zoomu 8, a niżej mapa nie pokazuje budynków wcale.
      </p>
    </section>
  )
}
