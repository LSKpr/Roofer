import type { ReactNode } from 'react'
import type { Building, RegistryMatch } from '../api/client'

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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-right text-slate-100">{value}</dd>
    </div>
  )
}

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <section
      aria-label="Szczegóły budynku"
      className="flex max-h-[70vh] w-80 flex-col rounded-lg border border-slate-700 bg-slate-900/85 text-slate-100 shadow-lg backdrop-blur"
    >
      <header className="flex items-start justify-between gap-2 border-b border-slate-700 px-3 py-2">
        <h2 className="text-sm leading-snug font-semibold">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Zamknij"
          className="-mt-1 rounded px-1.5 text-lg leading-none text-slate-400 hover:bg-slate-800 hover:text-slate-100"
        >
          ×
        </button>
      </header>
      <div className="min-h-0 overflow-y-auto px-3 py-2 text-xs text-slate-300">{children}</div>
    </section>
  )
}

export function BuildingPanel({ building, loading, error, onClose }: BuildingPanelProps) {
  if (loading) {
    return (
      <Shell title="Szczegóły budynku" onClose={onClose}>
        <p className="text-slate-300">Wczytuję szczegóły…</p>
      </Shell>
    )
  }

  if (error) {
    return (
      <Shell title="Nie udało się wczytać budynku" onClose={onClose}>
        <p className="text-red-300">{error}</p>
      </Shell>
    )
  }

  if (!building) return null

  const listed = building.status === 'listed'
  const badge = listed
    ? { text: 'Zgłoszony w rejestrze', className: 'border-red-500/60 bg-red-500/20 text-red-200' }
    : { text: 'Niezgłoszony', className: 'border-slate-500/60 bg-slate-600/40 text-slate-200' }

  return (
    <Shell title={headerTitle(building)} onClose={onClose}>
      <p>
        <span className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${badge.className}`}>
          {badge.text}
        </span>
      </p>

      <dl className="mt-3 space-y-1">
        <Row label="Powierzchnia" value={areaLabel(building.areaM2)} />
        <Row
          label="Centroid (lng, lat)"
          value={`${building.centroid.lng.toFixed(5)}, ${building.centroid.lat.toFixed(5)}`}
        />
        {building.osmId ? <Row label="OpenStreetMap" value={building.osmId} /> : null}
      </dl>

      {listed ? (
        <div className="mt-3">
          <h3 className="text-xs font-semibold text-slate-200">Rekordy rejestru ({building.registryMatches.length})</h3>
          {building.registryMatches.length === 0 ? (
            <p className="mt-1 text-slate-400">Backend nie podał szczegółów rekordów.</p>
          ) : (
            <ul className="mt-1 space-y-2">
              {building.registryMatches.map((match, index) => (
                <li
                  key={match.sourceId ?? `${match.nrDzialki ?? 'rekord'}-${index}`}
                  className="rounded border border-slate-700 bg-slate-800/60 p-2"
                >
                  <p className="font-medium text-slate-100">{matchTitle(match)}</p>
                  <dl className="mt-1 space-y-0.5">
                    <Row label="Powierzchnia rekordu" value={areaLabel(match.recordAreaM2)} />
                    <Row label="Przekrycie" value={areaLabel(match.overlapM2)} />
                    <Row label="Udział w budynku" value={percentLabel(match.shareBuilding)} />
                    <Row label="Udział w rekordzie" value={percentLabel(match.shareRecord)} />
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="mt-3 text-slate-400">
          Tego budynku nie ma w rejestrze GeoAzbest, więc jest niezgłoszony. To nie jest dowód, że dach jest czysty —
          znaczy tylko, że nikt go nie zgłosił.
        </p>
      )}

      {building.otherIntersecting > 0 ? (
        <p className="mt-3 text-slate-400">
          Ten budynek przecina jeszcze {building.otherIntersecting} {recordsNoun(building.otherIntersecting)} rejestru,
          które nie spełniły reguły dopasowania. Część geometrii w rejestrze to obrysy działek, nie dachów, i takie
          przecięcia są odrzucane.
        </p>
      ) : null}

      <p className="mt-3 border-t border-slate-700 pt-2 text-slate-500">
        Rejestr GeoAzbest jest niekompletny i opisuje zgłoszone wyroby azbestowe w obiekcie, a nie potwierdzone
        pokrycie dachu. Poza statusem zgłoszenia stan dachu pozostaje nieznany.
      </p>
    </Shell>
  )
}
