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
      aria-label="Map legend"
      className={`w-80 rounded-card border border-hairline bg-surface px-5 py-4 text-ink shadow-[0_1px_3px_rgba(5,28,44,0.08)] ${className ?? ''}`}
    >
      <h2 className="label-micro">Legend</h2>
      <ul className="mt-2 space-y-1.5 text-sm">
        <li className="flex items-center gap-2.5">
          <span
            data-testid="legend-swatch"
            className="inline-block h-2 w-2 shrink-0"
            style={{ backgroundColor: LISTED_COLOR }}
          />
          Listed in the GeoAzbest register
        </li>
        <li className="flex items-center gap-2.5">
          <span
            data-testid="legend-swatch"
            className="inline-block h-2 w-2 shrink-0"
            style={{ backgroundColor: NOT_LISTED_COLOR }}
          />
          Not listed
        </li>
      </ul>

      {/*
        Bez tego zdania wylaczone podswietlenie jest cichym klamstwem: mapa jest wtedy szara
        i wyglada dokladnie tak, jakby w tym obszarze nikt nic nie zglosil — a legenda obok
        dalej tlumaczy czerwien, ktorej na ekranie nie ma.
      */}
      {!showRegistry && (
        <p data-testid="legend-registry-off" className="mt-3 border-t border-hairline pt-3 text-xs text-ink">
          Register highlighting is off: no red does not mean nobody reported anything. The report density shown when
          zoomed out is hidden too.
        </p>
      )}

      {/*
        Pasek rampy jest z plaskich pol, nie z gradientu CSS: gradienty sa poza jezykiem wizualnym,
        a kolory i tak pochodza z tej samej stalej co warstwa mapy.
      */}
      <div className="mt-4 border-t border-hairline pt-4">
        <h3 className="label-micro">Report density when zoomed out</h3>
        <div data-testid="legend-heat-ramp" className="mt-2 flex border border-hairline">
          {HEATMAP_RAMP_COLORS.map((color) => (
            <span key={color} data-testid="legend-heat-step" className="h-2 flex-1" style={{ backgroundColor: color }} />
          ))}
        </div>
        <div className="mt-1 flex justify-between">
          <span className="label-micro">Single reports</span>
          <span className="label-micro">Cluster</span>
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          Colour intensity is the density of buildings listed in the GeoAzbest register — not the amount of asbestos
          and not a level of risk.
        </p>
      </div>

      <p className="mt-4 border-t border-hairline pt-4 text-xs text-ink-faint">
        When zoomed out the map shows only listed buildings. An area with no colour means "nobody reported anything
        here", not "there is nothing there": a municipality that runs no inventory stays blank on this map.
      </p>
      <p className="mt-2 text-xs text-ink-faint">
        Building outlines appear from zoom {POLYGON_MIN_ZOOM} and only then can a single roof be clicked. The heat
        itself is not clickable — a grid cell is not a building.
      </p>
      <p className="mt-2 text-xs text-ink-faint">
        The register is incomplete: a building missing from it is not proof that the roof is clean — it only means
        nobody reported it.
      </p>
    </section>
  )
}
