/**
 * Kolory statusow trzymamy w stalych, zeby probka w legendzie nie rozjechala sie z mapa.
 * Wartosci sa te same, co tokeny `--color-listed` i `--color-not-listed` w index.css:
 * czerwien redakcyjna, nie ostrzegawcza, i szarosc — nigdy zielen.
 *
 * TODO: po scaleniu wziac te kolory z STATUS_COLORS w src/map/layers.ts — warstwy mapy maja
 * jeszcze stara palete (#EF4444 / #64748B) i trzeba ja zrownac z tokenami.
 */
export const LISTED_COLOR = '#c8102e'
export const NOT_LISTED_COLOR = '#9aa5ad'

type LegendProps = { className?: string }

export function Legend({ className }: LegendProps) {
  return (
    <section
      aria-label="Legenda mapy"
      className={`w-80 rounded-card border border-hairline bg-surface px-5 py-4 text-ink shadow-[0_1px_3px_rgba(5,28,44,0.08)] ${className ?? ''}`}
    >
      <h2 className="label-micro">Legenda</h2>
      <ul className="mt-2 space-y-1.5 text-sm">
        <li className="flex items-center gap-2.5">
          <span
            data-testid="legend-swatch"
            className="inline-block h-2 w-2 shrink-0"
            style={{ backgroundColor: LISTED_COLOR }}
          />
          Zgłoszony w rejestrze GeoAzbest
        </li>
        <li className="flex items-center gap-2.5">
          <span
            data-testid="legend-swatch"
            className="inline-block h-2 w-2 shrink-0"
            style={{ backgroundColor: NOT_LISTED_COLOR }}
          />
          Niezgłoszony
        </li>
      </ul>
      <p className="mt-4 border-t border-hairline pt-4 text-xs text-ink-faint">
        Rejestr jest niekompletny: brak budynku w rejestrze nie jest dowodem, że dach jest czysty — znaczy tylko, że
        nikt go nie zgłosił.
      </p>
      <p className="mt-2 text-xs text-ink-faint">
        Po oddaleniu mapy widoczne są tylko zgłoszone budynki, i to jako punkty. Obrysy pojawiają się od zoomu 14,
        punkty od zoomu 8, a niżej mapa nie pokazuje budynków wcale.
      </p>
    </section>
  )
}
