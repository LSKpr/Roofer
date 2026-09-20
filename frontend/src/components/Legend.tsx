import { HEATMAP_RAMP_COLORS, POLYGON_MIN_ZOOM, STATUS_COLORS } from '../map/layers'

/**
 * Kolory probek bierzemy z warstw mapy (`src/map/layers.ts`), a nie z wlasnych hexow — inaczej
 * legenda tlumaczylaby kolory, ktorych na mapie juz nie ma. Tam tez stoi powod, dla ktorego hexy
 * sa zdublowane wobec tokenow `--color-listed` i `--color-not-listed`: MapLibre nie czyta CSS.
 */
export const LISTED_COLOR = STATUS_COLORS.listed
export const NOT_LISTED_COLOR = STATUS_COLORS.notListed

type LegendProps = {
  className?: string
  /** Stan przelacznika rejestru. Domyslnie wlaczony, czyli mapa jest taka, jak opisuje legenda. */
  showRegistry?: boolean
}

export function Legend({ className, showRegistry = true }: LegendProps) {
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

      {/*
        Bez tego zdania wylaczone podswietlenie jest cichym klamstwem: mapa jest wtedy szara
        i wyglada dokladnie tak, jakby w tym obszarze nikt nic nie zglosil — a legenda obok
        dalej tlumaczy czerwien, ktorej na ekranie nie ma.
      */}
      {!showRegistry && (
        <p data-testid="legend-registry-off" className="mt-3 border-t border-hairline pt-3 text-xs text-ink">
          Podświetlenie rejestru jest wyłączone: brak czerwieni nie znaczy, że nikt nic nie zgłosił. Ukryte jest też
          zagęszczenie zgłoszeń po oddaleniu.
        </p>
      )}

      {/*
        Pasek rampy jest z plaskich pol, nie z gradientu CSS: gradienty sa poza jezykiem wizualnym,
        a kolory i tak pochodza z tej samej stalej co warstwa mapy.
      */}
      <div className="mt-4 border-t border-hairline pt-4">
        <h3 className="label-micro">Zagęszczenie zgłoszeń po oddaleniu</h3>
        <div data-testid="legend-heat-ramp" className="mt-2 flex border border-hairline">
          {HEATMAP_RAMP_COLORS.map((color) => (
            <span key={color} data-testid="legend-heat-step" className="h-2 flex-1" style={{ backgroundColor: color }} />
          ))}
        </div>
        <div className="mt-1 flex justify-between">
          <span className="label-micro">Pojedyncze zgłoszenia</span>
          <span className="label-micro">Skupisko</span>
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          Intensywność koloru to zagęszczenie budynków zgłoszonych w rejestrze GeoAzbest — nie ilość azbestu i nie
          poziom ryzyka.
        </p>
      </div>

      <p className="mt-4 border-t border-hairline pt-4 text-xs text-ink-faint">
        Po oddaleniu mapa pokazuje wyłącznie zgłoszone budynki. Obszar bez koloru znaczy „nikt nic tu nie zgłosił", a
        nie „nic tam nie ma": gmina, która nie prowadzi inwentaryzacji, zostaje na tej mapie pusta.
      </p>
      <p className="mt-2 text-xs text-ink-faint">
        Obrysy budynków pojawiają się od zoomu {POLYGON_MIN_ZOOM} i dopiero wtedy można kliknąć pojedynczy dach.
        W samo ciepło kliknąć się nie da — komórka siatki nie jest budynkiem.
      </p>
      <p className="mt-2 text-xs text-ink-faint">
        Rejestr jest niekompletny: brak budynku w rejestrze nie jest dowodem, że dach jest czysty — znaczy tylko, że
        nikt go nie zgłosił.
      </p>
    </section>
  )
}
