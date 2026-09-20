import type { ReactNode } from 'react'
import type { Building, RegistryMatch } from '../api/client'
import { useRoofAnalysis } from '../hooks/useRoofAnalysis'
import { buildingTypeLabel, buildingTypeName } from '../lib/osmBuildingType'
import { RoofAnalysis } from './RoofAnalysis'
import { RoofPhoto } from './RoofPhoto'

type BuildingPanelProps = {
  building: Building | null
  loading: boolean
  error: string | null
  onClose: () => void
}

const AREA_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

function areaLabel(squareMeters: number): string {
  return `${AREA_FORMAT.format(squareMeters)} m²`
}

/** Udzialy przychodza z backendu jako ulamek 0–1. */
function percentLabel(share: number): string {
  return `${Math.round(share * 100)}%`
}

/**
 * Nazwa, a jak jej nie ma — nazwa rodzaju z OSM. `kind` (`fclass`) tu nie wchodzi, bo dla wszystkich
 * 2,58 mln budynkow ma wartosc „building" i w naglowku karty wygladalo to jak awaria.
 */
function headerTitle(building: Building): string {
  return building.name?.trim() || buildingTypeName(building.osmType) || 'Unnamed building'
}

/** Numer dzialki jest jedynym opisowym atrybutem rejestru; bez niego zostaje identyfikator zrodla. */
function matchTitle(match: RegistryMatch): string {
  const parcel = match.nrDzialki?.trim()
  if (parcel) return `Parcel ${parcel}`
  const source = match.sourceId?.trim()
  if (source) return `Record ${source}`
  return 'Record with no parcel number'
}

/** Angielska liczba mnoga: 1 record, wiecej records — polska odmiana 2-4 nie ma tu odpowiednika. */
function recordsNoun(count: number): string {
  return count === 1 ? 'record' : 'records'
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
      aria-label="Building details"
      className="flex max-h-[80vh] w-88 flex-col rounded-card border border-hairline bg-surface text-ink shadow-[0_1px_3px_rgba(5,28,44,0.08)]"
    >
      <header className="flex items-start justify-between gap-3 border-b border-hairline px-5 pt-3 pb-3">
        <div>
          <p className="label-micro">Building card</p>
          <h2 className="font-display text-base leading-snug text-ink">{title}</h2>
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

export function BuildingPanel({ building, loading, error, onClose }: BuildingPanelProps) {
  // Hook musi stac przed wyjsciami warunkowymi; dla braku budynku sam nie odpytuje niczego.
  const roof = useRoofAnalysis(building?.id ?? null)

  if (loading) {
    return (
      <Shell title="Building details" onClose={onClose}>
        <p className="text-ink-muted">Loading details…</p>
      </Shell>
    )
  }

  if (error) {
    return (
      <Shell title="Could not load the building" onClose={onClose}>
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
          <p className="label-micro">Roof area</p>
          <p className="font-display mt-0.5 text-2xl leading-none text-ink">{areaLabel(building.areaM2)}</p>
        </div>
        <div className="text-right">
          <p className="label-micro">Register status</p>
          {/* Status to kwadratowa kropka i tekst, nie kolorowa pigulka: rejestr nie jest ostrzezeniem. */}
          <p className="mt-1.5 flex items-center justify-end gap-2 text-ink">
            <span
              data-testid="status-dot"
              className={`inline-block h-2 w-2 shrink-0 ${listed ? 'bg-listed' : 'bg-not-listed'}`}
            />
            {listed ? 'Listed in the register' : 'Not listed'}
          </p>
        </div>
      </div>

      <Section title="Roof image">
        {/* `key` zeruje stan wczytywania przy przejsciu na inny budynek — karta sie nie przemontowuje.
            `roofImage` idzie dalej nietkniete: podpis pod kadrem podaje dzien nalotu i krawedz ramki
            tylko wtedy, gdy backend je zna, a karta nie ma prawa tych liczb uzupelniac. */}
        <RoofPhoto key={building.id} buildingId={building.id} roofImage={building.roofImage} />
      </Section>

      <Section title="Roof covering analysis">
        <RoofAnalysis analysis={roof.analysis} loading={roof.loading} error={roof.error} />
      </Section>

      <Section title="Building data">
        <dl>
          {buildingType ? <Row label="Type (OSM)" value={buildingType} /> : null}
          <Row
            label="Centroid (lng, lat)"
            value={`${building.centroid.lng.toFixed(5)}, ${building.centroid.lat.toFixed(5)}`}
          />
          {/* Identyfikator budynku JEST identyfikatorem z OSM, wiec da sie po nim znalezc obiekt
              na openstreetmap.org — w przeciwienstwie do dawnego klucza z sekwencji. */}
          <Row label="OpenStreetMap" value={String(building.id)} />
        </dl>
      </Section>

      {listed ? (
        <Section title={`Register records (${building.registryMatches.length})`}>
          {building.registryMatches.length === 0 ? (
            <p className="text-ink-muted">The backend did not return record details.</p>
          ) : (
            <ul>
              {building.registryMatches.map((match, index) => (
                <li key={match.sourceId ?? `${match.nrDzialki ?? 'rekord'}-${index}`} className="pt-3 first:pt-0">
                  <p className="text-ink">{matchTitle(match)}</p>
                  <dl className="mt-1.5">
                    <Row label="Record area" value={areaLabel(match.recordAreaM2)} />
                    <Row label="Overlap" value={areaLabel(match.overlapM2)} />
                    <Row label="Share of the building" value={percentLabel(match.shareBuilding)} />
                    <Row label="Share of the record" value={percentLabel(match.shareRecord)} />
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </Section>
      ) : (
        <Section title="GeoAzbest register">
          <p className="text-ink-muted">
            This building is not in the register, so it is not listed. That is not proof that the roof is clean — it
            only means nobody reported it.
          </p>
        </Section>
      )}

      {building.otherIntersecting > 0 ? (
        <p className="mt-4 text-xs text-ink-faint">
          This building also intersects {building.otherIntersecting} register{' '}
          {recordsNoun(building.otherIntersecting)} that did not meet the matching rule — some register geometries are
          parcel outlines, not roof outlines.
        </p>
      ) : null}

      <p className="mt-4 border-t border-hairline pt-4 text-xs text-ink-faint">
        The register is incomplete and lists reported asbestos products in a structure, not confirmed roof covering.
        Beyond the reporting status, the condition of the roof remains unknown.
      </p>
    </Shell>
  )
}
