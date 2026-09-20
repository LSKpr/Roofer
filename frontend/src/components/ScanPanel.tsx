import type { ReactNode } from 'react'
import type { AreaAnalysis, AreaModelLimits, AreaScan, ListedBuilding } from '../api/client'
import { recountStats } from '../lib/modelStats'
import { ThresholdSlider } from './ThresholdSlider'

type ScanPanelProps = {
  scan: AreaScan | null
  loading: boolean
  error: string | null
  onClose: () => void
  onPickBuilding: (id: number) => void
  /** Wynik modelu dla tego samego prostokata; `null`, dopoki nikt nie zlecil analizy. */
  analysis: AreaAnalysis | null
  analysisLoading: boolean
  analysisError: string | null
  onAnalyse: () => void
  /** Limity modelu z backendu; `null`, gdy backend ich nie poda — wtedy nie blokujemy przycisku. */
  modelLimits: AreaModelLimits | null
  /**
   * Prog podejrzenia wybrany suwakiem; `null` znaczy „nikt go nie ruszal" i wtedy obowiazuje prog
   * z odpowiedzi modelu. Stan trzyma `App`, bo ten sam prog filtruje obrysy na mapie.
   */
  threshold: number | null
  onThresholdChange: (value: number) => void
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
function Row({ label, value, muted = false }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-t border-hairline py-1.5 first:border-t-0 first:pt-0">
      <dt className="label-micro">{label}</dt>
      {/* Wyciszona wartosc to nazwa modelu: identyfikator do zacytowania, nie liczba do czytania. */}
      <dd className={`min-w-0 truncate text-right ${muted ? 'text-ink-faint' : 'text-ink'}`}>{value}</dd>
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

/** Jedyna liczba mnoga w sekcji modelu: 1 roof, kazda inna liczba roofs. */
function roofsLabel(count: number): string {
  return `${NUMBER_FORMAT.format(count)} ${count === 1 ? 'roof' : 'roofs'}`
}

/**
 * Powod, dla ktorego model nie przyjmie tego obszaru — albo `null`, gdy przyjmie.
 *
 * Liczba budynkow jest znana z wyniku skanu, a powierzchnia z tego samego wyniku, wiec powod da
 * sie podac przed kliknieciem. Limity pochodza z backendu: bez nich nie blokujemy przycisku,
 * bo zgadywanie cudzych limitow konczy sie blokada tam, gdzie zapytanie by przeszlo.
 */
function limitReason(scan: AreaScan, limits: AreaModelLimits | null): string | null {
  if (limits === null) return null
  if (scan.stats.total > limits.maxBuildings) {
    const max = NUMBER_FORMAT.format(limits.maxBuildings)
    return `The model accepts up to ${max} buildings; this area has ${NUMBER_FORMAT.format(scan.stats.total)}.`
  }
  if (scan.areaKm2 > limits.maxAreaKm2) {
    return `The model accepts up to ${km2Label(limits.maxAreaKm2)}; this selection is ${km2Label(scan.areaKm2)}.`
  }
  return null
}

/** Brak oceny to nie jest ocena „nic nie widac" — bez tego zdania zera w tabeli klamia. */
function noResultNote(count: number): string {
  return `${roofsLabel(count)} got no score (too little detail, greenery, or no imagery) — that is not the same as a roof the model saw nothing on.`
}

/**
 * Zgloszony dach bez flagi modelu jest najlatwiejszy do zlego odczytania: wyglada na odwolanie
 * zgloszenia. Model nie ma takiej mocy, wiec mowimy to wprost.
 */
function listedNotFlaggedNote(count: number): string {
  const subject = count === 1 ? '1 listed roof was' : `${NUMBER_FORMAT.format(count)} listed roofs were`
  return `${subject} not flagged by the model. That does not mean the asbestos is gone — the model may not recognise it, or the roof may look different from above.`
}

/**
 * Kolor podejrzenia. Ten sam token nosi warstwa modelu na mapie, wiec kropka przy liczbie
 * prowadzacej i poligon pod nia mowia tym samym kolorem.
 */
const SUSPECTED_DOT = 'bg-suspected'

/**
 * Prog jest decyzja patrzacego, nie wlasnoscia modelu: skutecznosc podana przez autora zmierzono
 * przy progu domyslnym, a suwak przesuwa kompromis, nie jakosc oceny.
 */
const THRESHOLD_NOTE =
  'The threshold is your decision, not a property of the model: both figures above were measured at the model default, and moving the slider trades false alarms against missed roofs rather than changing how well the model sees.'

/**
 * Ocena ponizej progu nie jest werdyktem o dachu. Bez tego zdania suwak czytaloby sie jako
 * „powyzej jest azbest, ponizej go nie ma", a model porownuje tylko wyglad pokrycia na zdjeciu.
 */
const BELOW_THRESHOLD_NOTE =
  'A roof below the threshold is not cleared: a lower score only means the model sees less resemblance to corrugated grey sheeting, never that the roof is without asbestos.'

/** Bez pelnej listy ocen nie ma z czego przeliczyc calosci — patrz komentarz w lib/modelStats.ts. */
const TRUNCATED_THRESHOLD_NOTE =
  'The threshold cannot be moved here: the list of roofs is truncated, so a recount would describe only the roofs that arrived, not the whole area.'

/** Liczby modelu w kolejnosci czytania: najpierw niezgloszone z flaga, potem cala reszta. */
function ModelNumbers({
  analysis,
  threshold,
  onThresholdChange,
}: {
  analysis: AreaAnalysis
  threshold: number | null
  onThresholdChange: (value: number) => void
}) {
  // Wszystko, co zalezy od progu, liczy sie tutaj z ocen pojedynczych budynkow — model nie jest
  // pytany po raz drugi, bo tamta instancja przyjmuje 10 zapytan na minute i jedno naraz.
  const stats = recountStats(analysis, threshold ?? analysis.stats.threshold)
  return (
    <div>
      {/* Suwak nad liczbami: najpierw widac, od ktorej oceny liczymy flage, potem ile jej wyszlo.
          Przy przycietej liscie go nie ma, bo nie przeliczamy — zdanie nizej mowi dlaczego. */}
      {analysis.truncated ? null : (
        <ThresholdSlider
          value={stats.threshold}
          onChange={onThresholdChange}
          modelDefault={analysis.stats.threshold}
          className="mb-3.5 border-b border-hairline pb-3.5"
        />
      )}

      {/* Liczba prowadzaca calej aplikacji: dachy, ktorych nikt nie zglosil, a model cos na nich widzi. */}
      <p className="flex items-center gap-2">
        <span data-testid="suspected-dot" className={`inline-block h-2.5 w-2.5 shrink-0 ${SUSPECTED_DOT}`} />
        <span data-testid="suspected-not-listed" className="font-display text-4xl leading-none text-ink">
          {NUMBER_FORMAT.format(stats.suspectedNotListed)}
        </span>
      </p>
      <p className="label-micro mt-1.5">Not in the register, flagged by the model</p>

      <dl className="mt-3">
        <Row label="Roofs analysed" value={NUMBER_FORMAT.format(stats.analysed)} />
        <Row label="No result from the model" value={NUMBER_FORMAT.format(stats.noResult)} />
        <Row
          label="Flagged by the model"
          value={`${NUMBER_FORMAT.format(stats.suspected)} (${percentLabel(stats.suspectedShare)})`}
        />
        <Row label="Flagged and already listed" value={NUMBER_FORMAT.format(stats.suspectedListed)} />
        <Row label="Listed but not flagged" value={NUMBER_FORMAT.format(stats.listedNotSuspected)} />
        <Row label="Roof area flagged" value={areaLabel(stats.suspectedRoofAreaM2)} />
        {stats.modelName ? <Row label="Model" value={stats.modelName} muted={true} /> : null}
      </dl>

      {/* Bez tych zdan sekcja klamie: model ocenia wyglad pokrycia na zdjeciu, nie stan prawny dachu. */}
      <div className="mt-3 space-y-1 text-xs text-ink-faint">
        <p>Orange marks what the model sees on a photo, not a fact from the register.</p>
        <p>The model reports 77% accuracy and 63% asbestos recall, so treat a flag as a hint for an inspection.</p>
        <p>{THRESHOLD_NOTE}</p>
        <p>{BELOW_THRESHOLD_NOTE}</p>
        {stats.noResult > 0 ? <p>{noResultNote(stats.noResult)}</p> : null}
        {stats.listedNotSuspected > 0 ? <p>{listedNotFlaggedNote(stats.listedNotSuspected)}</p> : null}
        {analysis.truncated ? (
          <>
            <p>The list of roofs is truncated, so the map shows fewer of them than the numbers above count.</p>
            <p>{TRUNCATED_THRESHOLD_NOTE}</p>
          </>
        ) : null}
      </div>
    </div>
  )
}

/**
 * Ocena modelu dla calego obszaru: osobny krok, nie automat po skanie.
 *
 * Model ma twarde limity i liczy kilka sekund, wiec uzytkownik decyduje, czy go uruchomic —
 * a gdy obszar sie nie miesci, powod stoi przy wylaczonym przycisku, zanim padnie klikniecie.
 */
function ModelSection({
  scan,
  analysis,
  loading,
  error,
  onAnalyse,
  modelLimits,
  threshold,
  onThresholdChange,
}: {
  scan: AreaScan
  analysis: AreaAnalysis | null
  loading: boolean
  error: string | null
  onAnalyse: () => void
  modelLimits: AreaModelLimits | null
  threshold: number | null
  onThresholdChange: (value: number) => void
}) {
  const reason = limitReason(scan, modelLimits)

  return (
    <Section title="Model analysis">
      {loading ? (
        // Zadanie trwa kilka sekund; bez tego zdania panel wyglada na zepsuty.
        <p className="text-ink-muted">Analysing {roofsLabel(scan.stats.total)}…</p>
      ) : analysis ? (
        <ModelNumbers analysis={analysis} threshold={threshold} onThresholdChange={onThresholdChange} />
      ) : (
        <div>
          <button
            type="button"
            onClick={onAnalyse}
            disabled={reason !== null}
            className={
              reason === null
                ? 'rounded-card border border-ink bg-ink px-3 py-1.5 text-xs leading-none text-surface hover:opacity-90'
                : 'rounded-card border border-hairline bg-surface px-3 py-1.5 text-xs leading-none text-ink-faint'
            }
          >
            Analyse roofs with the model
          </button>
          {reason ? <p className="mt-2 text-xs text-ink-muted">{reason}</p> : null}
          {error ? <p className="mt-2 text-listed">{error}</p> : null}
        </div>
      )}
    </Section>
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

export function ScanPanel({
  scan,
  loading,
  error,
  onClose,
  onPickBuilding,
  analysis,
  analysisLoading,
  analysisError,
  onAnalyse,
  modelLimits,
  threshold,
  onThresholdChange,
}: ScanPanelProps) {
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

      {/* Ocena modelu stoi pod calym rejestrem: to drugi krok i inne zrodlo, wiec nie miesza sie
          z liczbami zgloszen ani z zastrzezeniem o rejestrze. */}
      <ModelSection
        scan={scan}
        analysis={analysis}
        loading={analysisLoading}
        error={analysisError}
        onAnalyse={onAnalyse}
        modelLimits={modelLimits}
        threshold={threshold}
        onThresholdChange={onThresholdChange}
      />
    </Shell>
  )
}
