import type { ReactNode } from 'react'
import type { Building, RegistryMatch } from '../api/client'
import { useRoofAnalysis } from '../hooks/useRoofAnalysis'
import { buildingTypeLabel } from '../lib/osmBuildingType'
import { RoofAnalysis } from './RoofAnalysis'
import { RoofPhoto } from './RoofPhoto'

type BuildingPanelProps = {
  building: Building | null
  loading: boolean
  error: string | null
  onClose: () => void
}

const AREA_FORMAT = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 0 })

function areaLabel(squareMeters: number): string {
  return `${AREA_FORMAT.format(squareMeters)} m²`
}

/** Udzialy przychodza z backendu jako ulamek 0–1. */
function percentLabel(share: number): string {
  return `${Math.round(share * 100)}%`
}

function headerTitle(building: Building): string {
  return building.name?.trim() || building.kind?.trim() || 'Budynek bez nazwy'
}

/** Numer dzialki jest jedynym opisowym atrybutem rejestru; bez niego zostaje identyfikator zrodla. */
function matchTitle(match: RegistryMatch): string {
  const parcel = match.nrDzialki?.trim()
  if (parcel) return `Działka ${parcel}`
  const source = match.sourceId?.trim()
  if (source) return `Rekord ${source}`
  return 'Rekord bez numeru działki'
}

/** Polska odmiana: 1 rekord, 2–4 rekordy, inaczej rekordow. */
function recordsNoun(count: number): string {
  if (count === 1) return 'rekord'
  const lastTwo = count % 100
  const last = count % 10
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return 'rekordy'
  return 'rekordów'
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

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <section
      aria-label="Szczegóły budynku"
      className="flex max-h-[80vh] w-88 flex-col rounded-card border border-hairline bg-surface text-ink shadow-[0_1px_3px_rgba(5,28,44,0.08)]"
    >
      <header className="flex items-start justify-between gap-3 border-b border-hairline px-5 pt-3 pb-3">
        <div>
          <p className="label-micro">Karta budynku</p>
          <h2 className="font-display text-base leading-snug text-ink">{title}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Zamknij"
          className="-mt-1 -mr-2 rounded-card px-2 py-1 text-base leading-none text-ink-faint hover:bg-surface-muted hover:text-ink"
        >
          ×
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm text-ink-muted">{children}</div>
    </section>
  )
}

export function BuildingPanel({ building, loading, error, onClose }: BuildingPanelProps) {
  // Hook musi stac przed wyjsciami warunkowymi; dla braku budynku sam nie odpytuje niczego.
  const roof = useRoofAnalysis(building?.id ?? null)

  if (loading) {
    return (
      <Shell title="Szczegóły budynku" onClose={onClose}>
        <p className="text-ink-muted">Wczytuję szczegóły…</p>
      </Shell>
    )
  }

  if (error) {
    return (
      <Shell title="Nie udało się wczytać budynku" onClose={onClose}>
        <p className="text-listed">{error}</p>
      </Shell>
    )
  }

  if (!building) return null

  const listed = building.status === 'listed'
  const buildingType = buildingTypeLabel(building.osmType)

  return (
    <Shell title={headerTitle(building)} onClose={onClose}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="label-micro">Powierzchnia dachu</p>
          <p className="font-display mt-0.5 text-2xl leading-none text-ink">{areaLabel(building.areaM2)}</p>
        </div>
        <div className="text-right">
          <p className="label-micro">Status w rejestrze</p>
          {/* Status to kwadratowa kropka i tekst, nie kolorowa pigulka: rejestr nie jest ostrzezeniem. */}
          <p className="mt-1.5 flex items-center justify-end gap-2 text-ink">
            <span
              data-testid="status-dot"
              className={`inline-block h-2 w-2 shrink-0 ${listed ? 'bg-listed' : 'bg-not-listed'}`}
            />
            {listed ? 'Zgłoszony w rejestrze' : 'Niezgłoszony'}
          </p>
        </div>
      </div>

      <Section title="Zdjęcie dachu">
        {/* `key` zeruje stan wczytywania przy przejsciu na inny budynek — karta sie nie przemontowuje. */}
        <RoofPhoto key={building.id} buildingId={building.id} />
      </Section>

      <Section title="Analiza pokrycia dachu">
        <RoofAnalysis analysis={roof.analysis} loading={roof.loading} error={roof.error} />
      </Section>

      <Section title="Dane budynku">
        <dl>
          {buildingType ? <Row label="Rodzaj (OSM)" value={buildingType} /> : null}
          <Row
            label="Centroid (lng, lat)"
            value={`${building.centroid.lng.toFixed(5)}, ${building.centroid.lat.toFixed(5)}`}
          />
          {building.osmId ? <Row label="OpenStreetMap" value={building.osmId} /> : null}
        </dl>
      </Section>

      {listed ? (
        <Section title={`Rekordy rejestru (${building.registryMatches.length})`}>
          {building.registryMatches.length === 0 ? (
            <p className="text-ink-muted">Backend nie podał szczegółów rekordów.</p>
          ) : (
            <ul>
              {building.registryMatches.map((match, index) => (
                <li key={match.sourceId ?? `${match.nrDzialki ?? 'rekord'}-${index}`} className="pt-3 first:pt-0">
                  <p className="text-ink">{matchTitle(match)}</p>
                  <dl className="mt-1.5">
                    <Row label="Powierzchnia rekordu" value={areaLabel(match.recordAreaM2)} />
                    <Row label="Przekrycie" value={areaLabel(match.overlapM2)} />
                    <Row label="Udział w budynku" value={percentLabel(match.shareBuilding)} />
                    <Row label="Udział w rekordzie" value={percentLabel(match.shareRecord)} />
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </Section>
      ) : (
        <Section title="Rejestr GeoAzbest">
          <p className="text-ink-muted">
            Tego budynku nie ma w rejestrze, więc jest niezgłoszony. To nie jest dowód, że dach jest czysty — znaczy
            tylko, że nikt go nie zgłosił.
          </p>
        </Section>
      )}

      {building.otherIntersecting > 0 ? (
        <p className="mt-4 text-xs text-ink-faint">
          Ten budynek przecina jeszcze {building.otherIntersecting} {recordsNoun(building.otherIntersecting)} rejestru,
          które nie spełniły reguły dopasowania — część geometrii w rejestrze to obrysy działek, nie dachów.
        </p>
      ) : null}

      <p className="mt-4 border-t border-hairline pt-4 text-xs text-ink-faint">
        Rejestr jest niekompletny i opisuje zgłoszone wyroby azbestowe w obiekcie, a nie potwierdzone pokrycie dachu.
        Poza statusem zgłoszenia stan dachu pozostaje nieznany.
      </p>
    </Shell>
  )
}
