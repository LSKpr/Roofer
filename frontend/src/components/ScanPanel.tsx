import type { ReactNode } from 'react'
import type { AreaScan, ListedBuilding } from '../api/client'

type ScanPanelProps = {
  scan: AreaScan | null
  loading: boolean
  error: string | null
  onClose: () => void
  onPickBuilding: (id: number) => void
}

const NUMBER_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const KM2_FORMAT = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

function areaLabel(squareMeters: number): string {
  return `${NUMBER_FORMAT.format(squareMeters)} m²`
}

function km2Label(squareKilometers: number): string {
  return `${KM2_FORMAT.format(squareKilometers)} km²`
}

/** Udzial przychodzi z backendu jako ulamek 0–1. W tekscie czyta sie go jako liczbe calkowita. */
function percentLabel(share: number): string {
  return `${Math.round(share * 100)}%`
}

/**
 * Szerokosc paska udzialu. Zamiast biblioteki do wykresow zwykly div z szerokoscia w procentach —
 * jedna liczba i jedna linia nie potrzebuja 300 kB zaleznosci. Zaokraglenie do dziesiatej czesci
 * procenta jest drobniejsze niz piksel na tym pasku, wiec pasek nie klamie wzgledem liczby.
 */
function barWidth(share: number): string {
  const percent = Math.min(Math.max(share * 100, 0), 100)
  return `${percent.toFixed(1)}%`
}

/** Jedyna liczba mnoga, jakiej ten panel potrzebuje: 1 building, kazda inna liczba buildings. */
function buildingsNoun(count: number): string {
  return count === 1 ? 'building' : 'buildings'
}

/** Numer dzialki jest jedynym opisowym atrybutem rejestru; bez niego zostaje sam brak numeru. */
function parcelLabel(building: ListedBuilding): string {
  const parcel = building.nrDzialki?.trim()
  return parcel ? `Parcel ${parcel}` : 'No parcel number'
}

/**
 * Backend oddaje najwyzej 500 zgloszonych budynkow i zglasza to polem `truncated`. Bez tego
 * zdania przycieta lista wygladalaby jak komplet, a statystyki jak niezgodne z nia.
 */
function truncationNote(scan: AreaScan): string {
  const shown = NUMBER_FORMAT.format(scan.listedBuildings.length)
  const listed = NUMBER_FORMAT.format(scan.stats.listed)
  return `The list is truncated: showing ${shown} of ${listed} listed buildings. The statistics above cover the whole selected area.`
}

/** Para etykieta/wartosc: mikropodpis po lewej, wartosc po prawej, wiersze rozdziela wlosowa linia. */
function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-t border-hairline py-1.5 first:border-t-0 first:pt-0">
      <dt className="label-micro">{label}</dt>
      <dd className="text-right text-ink">{value}</dd>
    </div>
  )
}

/** Sekcje rozdziela wlosowa linia i swiatlo, nigdy kolorowy blok. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-4 border-t border-hairline pt-4">
      <h3 className="label-micro">{title}</h3>
      <div className="mt-2">{children}</div>
    </section>
  )
}

/** Rejestr jest niekompletny i nie ma z czego wnioskowac o stanie dachu — to musi byc widoczne. */
function RegistryNote() {
  return (
    <p className="mt-4 border-t border-hairline pt-4 text-xs text-ink-faint">
      The GeoAzbest register is incomplete and records reports of asbestos-containing products, not the condition of
      roofs. A building missing from the register is not proof that the roof is clean — it only means nobody reported
      it.
    </p>
  )
}

/** Rodzic odpowiada za pozycjonowanie panelu; karta zna tylko swoja szerokosc i wysokosc. */
function Shell({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <section
      aria-label="Area scan result"
      className="flex max-h-[80vh] w-88 flex-col rounded-card border border-hairline bg-surface text-ink shadow-[0_1px_3px_rgba(5,28,44,0.08)]"
    >
      <header className="flex items-start justify-between gap-3 border-b border-hairline px-5 pt-3 pb-3">
        <div>
          <p className="label-micro">Selected rectangle</p>
          <h2 className="font-display text-base leading-snug text-ink">Area scan result</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="-mt-1 -mr-2 rounded-card px-2 py-1 text-base leading-none text-ink-faint hover:bg-surface-muted hover:text-ink"
        >
          ×
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm text-ink-muted">{children}</div>
    </section>
  )
}

export function ScanPanel({ scan, loading, error, onClose, onPickBuilding }: ScanPanelProps) {
  if (loading) {
    return (
      <Shell onClose={onClose}>
        <p className="text-ink-muted">Scanning the area…</p>
      </Shell>
    )
  }

  if (error) {
    return (
      <Shell onClose={onClose}>
        <p className="text-listed">{error}</p>
      </Shell>
    )
  }

  if (!scan) return null

  const { stats, listedBuildings, truncated } = scan

  // Pusty obszar to nie jest wynik zlozony z zer: zera wygladaja jak zmierzone i myla.
  if (stats.total === 0) {
    return (
      <Shell onClose={onClose}>
        <p className="text-ink-muted">There are no OpenStreetMap buildings in this area.</p>
        <dl className="mt-4 border-t border-hairline pt-4">
          <Row label="Selection area" value={km2Label(scan.areaKm2)} />
        </dl>
        <RegistryNote />
      </Shell>
    )
  }

  return (
    <Shell onClose={onClose}>
      {/* Liczba prowadzaca: udzial zgloszonych. Reszta panelu jest jej uzasadnieniem. */}
      <p className="font-display text-4xl leading-none text-ink">{percentLabel(stats.listedShare)}</p>
      <p className="label-micro mt-1.5">Share listed in the register</p>
      <p className="mt-1 text-ink-muted">
        {NUMBER_FORMAT.format(stats.listed)} of {NUMBER_FORMAT.format(stats.total)} {buildingsNoun(stats.total)}
      </p>

      <div className="mt-3 h-2 w-full border border-hairline bg-surface-muted">
        <div
          data-testid="listed-share-bar"
          className="h-full bg-listed"
          style={{ width: barWidth(stats.listedShare) }}
        />
      </div>

      <Section title="Area and buildings">
        <dl>
          <Row label="Selection area" value={km2Label(scan.areaKm2)} />
          <Row label="Buildings in the area" value={NUMBER_FORMAT.format(stats.total)} />
          <Row label="Listed" value={NUMBER_FORMAT.format(stats.listed)} />
          <Row label="Not listed" value={NUMBER_FORMAT.format(stats.notListed)} />
          <Row label="Roof area" value={areaLabel(stats.roofAreaM2)} />
          <Row label="Roof area of listed buildings" value={areaLabel(stats.listedRoofAreaM2)} />
          <Row label="Register records in the area" value={NUMBER_FORMAT.format(stats.registryRecords)} />
        </dl>
      </Section>

      <Section title={`Listed buildings (${NUMBER_FORMAT.format(stats.listed)})`}>
        {listedBuildings.length === 0 ? (
          <p className="text-ink-muted">No building from this area is in the register.</p>
        ) : (
          // Lista bywa dluga (backend oddaje do 500 pozycji), wiec przewija sie sama,
          // a statystyki zostaja widoczne nad nia.
          <ul className="max-h-56 overflow-y-auto">
            {listedBuildings.map((building) => (
              <li key={building.id} className="border-t border-hairline first:border-t-0">
                {/* Klikalny jest caly wiersz, nie link w tekscie: celem jest budynek na mapie. */}
                <button
                  type="button"
                  onClick={() => onPickBuilding(building.id)}
                  className="flex w-full items-baseline justify-between gap-4 py-2 text-left hover:bg-surface-muted"
                >
                  {/* Numery dzialek sa dlugie; obcinamy je, zeby powierzchnia zostala przy krawedzi. */}
                  <span className="min-w-0 truncate text-ink">{parcelLabel(building)}</span>
                  <span className="shrink-0 text-ink-muted">{areaLabel(building.areaM2)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {truncated ? <p className="mt-3 text-xs text-ink-faint">{truncationNote(scan)}</p> : null}
      </Section>

      <RegistryNote />
    </Shell>
  )
}
