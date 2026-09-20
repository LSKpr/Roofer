import { useEffect, useMemo, useState } from 'react'
import {
  fetchAreaLimits,
  fetchHealth,
  type AreaAnalysis,
  type AreaModelLimits,
  type Bounds,
  type Health,
  type Place,
  type RoofGeometry,
  type SuspectedRoof,
} from './api/client'
import { BasemapSwitcher } from './components/BasemapSwitcher'
import { BuildingPanel } from './components/BuildingPanel'
import { Legend } from './components/Legend'
import { RegistryToggle } from './components/RegistryToggle'
import { ScanPanel } from './components/ScanPanel'
import { SearchBox } from './components/SearchBox'
import { ZoomHint } from './components/ZoomHint'
import { useAreaAnalysis } from './hooks/useAreaAnalysis'
import { useAreaScan } from './hooks/useAreaScan'
import { useBuilding } from './hooks/useBuilding'
import { effectiveThreshold } from './lib/modelStats'
import { MapView, type MapFocus } from './map/MapView'
import { DEFAULT_BASEMAP, INITIAL_ZOOM, type BasemapId } from './map/basemap'

type BackendState =
  | { kind: 'checking' }
  | { kind: 'answered'; health: Health }
  | { kind: 'unreachable'; message: string }

const KM2_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/**
 * Stan backendu jest informacja diagnostyczna, nie trescia: zostaje kropka z podpowiedzia.
 * Wczesniej zajmowal cala belke nad mapa.
 */
function statusLabel(state: BackendState): { text: string; dot: string } {
  if (state.kind === 'checking') return { text: 'Checking the backend connection…', dot: 'bg-ink-faint' }
  if (state.kind === 'unreachable') return { text: `Backend unavailable: ${state.message}`, dot: 'bg-listed' }
  if (state.health.status === 'ok') return { text: `Backend OK · PostGIS ${state.health.postgis}`, dot: 'bg-accent' }
  return { text: `Backend without a database: ${state.health.detail ?? 'no details'}`, dot: 'bg-listed' }
}

/**
 * Mapa dostaje tylko te dachy, ktorych ocena siega obowiazujacego progu.
 *
 * Prog nie jest stala w kodzie: domyslnie przychodzi w odpowiedzi modelu, a suwak w panelu moze
 * go przesunac. Filtruje rodzic, bo to decyzja interfejsu: liczby w panelu i obrysy na mapie
 * musza pochodzic z tego samego progu, inaczej „14 niezgloszonych z flaga" nie zgadzaloby sie
 * z tym, co widac pomaranczowego. Prog liczy `effectiveThreshold`, czyli ten sam modul, ktory
 * przelicza liczby w panelu — przy przycietej liscie oddaje prog backendu.
 */
/** Budynek, ktory da sie narysowac: ocena powyzej progu i obrys od modelu. */
type DrawableRoof = SuspectedRoof & { geometry: RoofGeometry }

function aboveThreshold(analysis: AreaAnalysis | null, chosen: number | null): DrawableRoof[] | null {
  if (analysis === null) return null
  const threshold = effectiveThreshold(analysis, chosen)
  // Bez obrysu nie ma czego narysowac; w statystykach taki budynek i tak jest policzony.
  return analysis.buildings.filter(
    (roof): roof is DrawableRoof => roof.probability >= threshold && roof.geometry !== null,
  )
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
  /**
   * Podswietlenie rejestru. Domyslnie wlaczone, wiec mapa startuje tak jak dotad. Stan siedzi
   * tutaj, bo ta sama wartosc steruje kolorami w `MapView` i zdaniem w `Legend` — dwie kopie
   * rozjechalyby sie i legenda tlumaczylaby kolory, ktorych na mapie nie ma.
   */
  const [showRegistry, setShowRegistry] = useState(true)
  /**
   * Obszar, ktorego dotyczy wynik na ekranie. Trzyma go `App`, a nie modul rysowania: prostokat
   * jest stanem aplikacji (zyje tyle, co wynik), a rysowanie jest stanem interakcji z myszka
   * (konczy sie na `mouseup`). Dzieki temu obszar zostaje widoczny pod karta budynku i pod bledem.
   */
  const [scannedArea, setScannedArea] = useState<Bounds | null>(null)
  const [limitKm2, setLimitKm2] = useState<number | null>(null)
  /** Limity modelu sa twardsze niz limit skanu, wiec panel trzyma je osobno. */
  const [modelLimits, setModelLimits] = useState<AreaModelLimits | null>(null)
  const selection = useBuilding(selectedId)
  const scan = useAreaScan()
  /**
   * Ocena modelu jest drugim krokiem, nie skutkiem skanu: model przyjmuje 100 budynkow i 4 km2,
   * a liczy kilka sekund, wiec uruchamia ja klikniecie, a nie samo narysowanie prostokata.
   */
  const analysis = useAreaAnalysis()
  /**
   * Prog podejrzenia wybrany suwakiem. `null` znaczy „nikt go nie ruszal" i wtedy obowiazuje prog
   * z odpowiedzi modelu — dzieki temu nie trzymamy drugiej kopii tamtej liczby, a nowy wynik
   * zawsze startuje od progu, przy ktorym backend policzyl swoje statystyki. Stan siedzi tutaj,
   * bo ta sama wartosc liczy tabelke w `ScanPanel` i filtruje obrysy w `MapView`; dwie kopie
   * rozjechalyby sie i panel mowilby o innych dachach, niz widac na mapie.
   */
  const [threshold, setThreshold] = useState<number | null>(null)
  const suspectedRoofs = useMemo(() => aboveThreshold(analysis.analysis, threshold), [analysis.analysis, threshold])

  useEffect(() => {
    let current = true
    fetchHealth()
      .then((health) => current && setState({ kind: 'answered', health }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'unknown error'
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
      .then((limits) => {
        if (!current) return
        setLimitKm2(limits.maxAreaKm2)
        // Bez limitow modelu nie blokujemy przycisku: wtedy odpowiada sam backend i to jego
        // tekst zobaczy uzytkownik. Zgadywanie cudzych limitow blokowaloby dzialajace zadania.
        setModelLimits(limits.model ?? null)
      })
      .catch(() => undefined)
    return () => {
      current = false
    }
  }, [])

  const status = statusLabel(state)

  /**
   * Wynik i jego obszar sa jednym: zamkniecie panelu zdejmuje takze prostokat z mapy i ocene
   * modelu. Zostawiona ocena opisywalaby budynki z poprzedniego zaznaczenia, a jej pomaranczowe
   * obrysy wisialyby na mapie bez panelu, ktory je tlumaczy.
   */
  function clearScan() {
    scan.clear()
    analysis.clear()
    setScannedArea(null)
    // Prog nalezy do wyniku, nie do sesji: przy nastepnej ocenie obowiazuje znowu prog modelu.
    setThreshold(null)
  }

  function startDrawing() {
    // Karta budynku i wynik poprzedniego skanu zaslanialyby nowy wynik, a stary prostokat
    // zostalby na mapie obok nowego i nie daloby sie odczytac, ktorego dotycza liczby.
    setSelectedId(null)
    clearScan()
    setDrawing(true)
  }

  function handleDrawComplete(bounds: Bounds) {
    setDrawing(false)
    // Obszar zapamietujemy przed odpowiedzia backendu: przy bledzie („obszar za duzy") uzytkownik
    // tym bardziej musi widziec, co zaznaczyl, zeby poprawic zaznaczenie.
    setScannedArea(bounds)
    scan.run(bounds)
  }

  /** Model dostaje dokladnie ten prostokat, ktorego dotycza liczby na ekranie. */
  function analyseArea() {
    if (scannedArea === null) return
    // Nowa ocena przychodzi ze swoim progiem i to on obowiazuje; prog przesuniety przy
    // poprzednim wyniku opisywalby tamte dachy.
    setThreshold(null)
    analysis.run(scannedArea)
  }

  function handlePickBuilding(id: number) {
    setSelectedId(id)
    const picked = scan.scan?.listedBuildings.find((item) => item.id === id)
    if (picked) setFocus({ kind: 'point', center: [picked.centroid.lng, picked.centroid.lat], zoom: 17 })
  }

  const scanHint = drawing
    ? 'Drag a rectangle on the map'
    : limitKm2 !== null
      ? `Select a rectangle, max ${KM2_FORMAT.format(limitKm2)} km²`
      : 'Select a rectangle on the map'

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
        scannedArea={scannedArea}
        showRegistry={showRegistry}
        suspectedRoofs={suspectedRoofs}
      />

      {/* Warstwa paneli nie przechwytuje przeciagania mapy — klikalne sa tylko same panele. */}
      <div className="pointer-events-none absolute inset-0 z-10 flex flex-col justify-between gap-4 p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="pointer-events-auto w-88 rounded-card border border-hairline bg-surface shadow-[0_1px_3px_rgba(5,28,44,0.08)]">
            <div className="flex items-start justify-between gap-3 px-4 pt-3 pb-2.5">
              <div>
                <p className="font-display text-base leading-none text-ink">Roofer</p>
                <p className="label-micro mt-1.5">Asbestos register · Masovian Voivodeship</p>
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
                <p className="label-micro">Area scan</p>
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
                {drawing ? 'Cancel' : 'Select'}
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
            {/* Pod przelacznikiem podkladow: oba decyduja o tym, co widac na mapie, nie o danych. */}
            <div className="pointer-events-auto">
              <RegistryToggle checked={showRegistry} onChange={setShowRegistry} />
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
                  onClose={clearScan}
                  onPickBuilding={handlePickBuilding}
                  analysis={analysis.analysis}
                  analysisLoading={analysis.loading}
                  analysisError={analysis.error}
                  onAnalyse={analyseArea}
                  modelLimits={modelLimits}
                  threshold={threshold}
                  onThresholdChange={setThreshold}
                />
              )}
            </div>
          </div>
        </div>

        <div className="pointer-events-auto self-start">
          <Legend showRegistry={showRegistry} />
        </div>
      </div>
    </div>
  )
}
