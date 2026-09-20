import { useEffect, useState } from 'react'
import { fetchAreaLimits, fetchHealth, type Bounds, type Health, type Place } from './api/client'
import { BasemapSwitcher } from './components/BasemapSwitcher'
import { BuildingPanel } from './components/BuildingPanel'
import { Legend } from './components/Legend'
import { ScanPanel } from './components/ScanPanel'
import { SearchBox } from './components/SearchBox'
import { ZoomHint } from './components/ZoomHint'
import { useAreaScan } from './hooks/useAreaScan'
import { useBuilding } from './hooks/useBuilding'
import { MapView, type MapFocus } from './map/MapView'
import { DEFAULT_BASEMAP, INITIAL_ZOOM, type BasemapId } from './map/basemap'

type BackendState =
  | { kind: 'checking' }
  | { kind: 'answered'; health: Health }
  | { kind: 'unreachable'; message: string }

const KM2_FORMAT = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 0 })

/**
 * Stan backendu jest informacja diagnostyczna, nie trescia: zostaje kropka z podpowiedzia.
 * Wczesniej zajmowal cala belke nad mapa.
 */
function statusLabel(state: BackendState): { text: string; dot: string } {
  if (state.kind === 'checking') return { text: 'Sprawdzam połączenie z backendem…', dot: 'bg-ink-faint' }
  if (state.kind === 'unreachable') return { text: `Backend niedostepny: ${state.message}`, dot: 'bg-listed' }
  if (state.health.status === 'ok') return { text: `Backend ok · PostGIS ${state.health.postgis}`, dot: 'bg-accent' }
  return { text: `Backend bez bazy: ${state.health.detail ?? 'brak szczegolow'}`, dot: 'bg-listed' }
}

/** Nominatim oddaje bbox jako [south, west, north, east], a mapa chce [west, south, east, north]. */
function focusOn(place: Place): MapFocus {
  if (place.bbox) {
    const [south, west, north, east] = place.bbox
    return { kind: 'bounds', bounds: [west, south, east, north] }
  }
  // Adres bez prostokata: zoom 16 daje obrysy dachow, a nie sama heatmape zageszczenia.
  return { kind: 'point', center: [place.lng, place.lat], zoom: 16 }
}

export function App() {
  const [state, setState] = useState<BackendState>({ kind: 'checking' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [zoom, setZoom] = useState(INITIAL_ZOOM)
  const [focus, setFocus] = useState<MapFocus | null>(null)
  const [basemap, setBasemap] = useState<BasemapId>(DEFAULT_BASEMAP)
  const [drawing, setDrawing] = useState(false)
  const [limitKm2, setLimitKm2] = useState<number | null>(null)
  const selection = useBuilding(selectedId)
  const scan = useAreaScan()

  useEffect(() => {
    let current = true
    fetchHealth()
      .then((health) => current && setState({ kind: 'answered', health }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'nieznany blad'
        return current && setState({ kind: 'unreachable', message })
      })
    return () => {
      current = false
    }
  }, [])

  // Limit powierzchni zna backend; front go pokazuje, ale nie trzyma wlasnej kopii tej liczby.
  useEffect(() => {
    let current = true
    fetchAreaLimits()
      .then((limits) => current && setLimitKm2(limits.maxAreaKm2))
      .catch(() => undefined)
    return () => {
      current = false
    }
  }, [])

  const status = statusLabel(state)

  function startDrawing() {
    // Karta budynku i wynik poprzedniego skanu zaslanialyby nowy wynik.
    setSelectedId(null)
    scan.clear()
    setDrawing(true)
  }

  function handleDrawComplete(bounds: Bounds) {
    setDrawing(false)
    scan.run(bounds)
  }

  function handlePickBuilding(id: number) {
    setSelectedId(id)
    const picked = scan.scan?.listedBuildings.find((item) => item.id === id)
    if (picked) setFocus({ kind: 'point', center: [picked.centroid.lng, picked.centroid.lat], zoom: 17 })
  }

  const scanHint = drawing
    ? 'Przeciągnij ramkę na mapie'
    : limitKm2 !== null
      ? `Zaznacz prostokąt, maks. ${KM2_FORMAT.format(limitKm2)} km²`
      : 'Zaznacz prostokąt na mapie'

  return (
    <div className="relative h-full w-full">
      <MapView
        selectedId={selectedId}
        onSelect={setSelectedId}
        onZoomChange={setZoom}
        basemap={basemap}
        focus={focus}
        drawing={drawing}
        onDrawComplete={handleDrawComplete}
        onDrawCancel={() => setDrawing(false)}
      />

      {/* Warstwa paneli nie przechwytuje przeciagania mapy — klikalne sa tylko same panele. */}
      <div className="pointer-events-none absolute inset-0 z-10 flex flex-col justify-between gap-4 p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="pointer-events-auto w-88 rounded-card border border-hairline bg-surface shadow-[0_1px_3px_rgba(5,28,44,0.08)]">
            <div className="flex items-start justify-between gap-3 px-4 pt-3 pb-2.5">
              <div>
                <p className="font-display text-base leading-none text-ink">Roofer</p>
                <p className="label-micro mt-1.5">Rejestr azbestu · województwo mazowieckie</p>
              </div>
              <span
                title={status.text}
                className={`mt-1 inline-block h-1.5 w-1.5 shrink-0 ${status.dot}`}
                data-testid="backend-status"
              />
              <span className="sr-only">{status.text}</span>
            </div>

            <SearchBox onPick={(place) => setFocus(focusOn(place))} className="border-t border-hairline" />

            <div className="flex items-center justify-between gap-3 border-t border-hairline px-4 py-2.5">
              <div className="min-w-0">
                <p className="label-micro">Skan obszaru</p>
                <p className="mt-0.5 truncate text-xs text-ink-muted">{scanHint}</p>
              </div>
              <button
                type="button"
                onClick={drawing ? () => setDrawing(false) : startDrawing}
                className={
                  drawing
                    ? 'shrink-0 rounded-card border border-hairline bg-surface px-3 py-1.5 text-xs leading-none text-ink-muted hover:bg-surface-muted hover:text-ink'
                    : 'shrink-0 rounded-card border border-ink bg-ink px-3 py-1.5 text-xs leading-none text-surface hover:opacity-90'
                }
              >
                {drawing ? 'Anuluj' : 'Zaznacz'}
              </button>
            </div>
          </div>

          <div className="pointer-events-auto mt-1">
            <ZoomHint zoom={zoom} />
          </div>

          <div className="flex flex-col items-end gap-3">
            <div className="pointer-events-auto">
              <BasemapSwitcher value={basemap} onChange={setBasemap} />
            </div>
            <div className="pointer-events-auto">
              {selectedId !== null ? (
                <BuildingPanel
                  building={selection.building}
                  loading={selection.loading}
                  error={selection.error}
                  onClose={() => setSelectedId(null)}
                />
              ) : (
                <ScanPanel
                  scan={scan.scan}
                  loading={scan.loading}
                  error={scan.error}
                  onClose={scan.clear}
                  onPickBuilding={handlePickBuilding}
                />
              )}
            </div>
          </div>
        </div>

        <div className="pointer-events-auto self-start">
          <Legend />
        </div>
      </div>
    </div>
  )
}
