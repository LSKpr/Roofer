import type { ReactNode } from 'react'
import type { AreaAnalysis, AreaScan, ListedBuilding } from '../api/client'
import type { AreaAnalysisProgress } from '../hooks/useAreaAnalysis'
import { recountStats, selectFlaggedNotListed } from '../lib/modelStats'
import { FlaggedRoofs } from './FlaggedRoofs'
import { ThresholdSlider } from './ThresholdSlider'

type ScanPanelProps = {
  scan: AreaScan | null
  loading: boolean
  error: string | null
  onClose: () => void
  onPickBuilding: (id: number) => void
  /**
   * Wynik modelu dla tego samego prostokata; `null`, dopoki nikt nie zlecil analizy. W trakcie
   * pracy jest tu wynik CZESCIOWY — scalony z kawalkow, ktore juz splynely.
   */
  analysis: AreaAnalysis | null
  analysisLoading: boolean
  analysisError: string | null
  /** Postep analizy kawalek po kawalku; `null`, dopoki nie ma planu. */
  analysisProgress: AreaAnalysisProgress | null
  /** Plan pominal fragment zaznaczenia, bo byl za gesty na podzial — panel musi to powiedziec. */
  analysisSkipped: boolean
  onAnalyse: () => void
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
 * Gorna granica czasu na jeden dach. Zmierzone na lokalnej kopii uslugi: ten sam obszar 464 dachow
 * z kaflami w cache szedl 19,2 s, 24,3 s i 41,3 s w trzech kolejnych przebiegach — dwukrotny
 * rozrzut na tej samej pracy, bo laptopowy procesor zjezdza z taktowaniem. Sama inferencja to
 * 40-50 ms na dach i tego nie da sie skrocic; pobranie kafli dla nowego obszaru doklada
 * kilkanascie sekund.
 *
 * Dlatego mowimy „up to", a nie „about": przy takim rozrzucie kazda konkretna liczba jest
 * nieprawda w jedna albo w druga strone, a obietnica, ktora konczy sie wczesniej, jest uczciwsza
 * niz taka, ktora sie przedluza.
 */
const SECONDS_PER_ROOF = 0.18

/**
 * Szacowany czas oczekiwania. Przy pieciuset dachach zadanie idzie od poltorej do trzech minut
 * i bez tej informacji panel wyglada na zawieszony — a uzytkownik, ktory nie wie, ile czekac,
 * przerywa i zaraz placi za to samo drugi raz.
 */
function waitLabel(roofs: number): string {
  const seconds = Math.round(roofs * SECONDS_PER_ROOF)
  if (seconds < 15) return 'usually a few seconds'
  if (seconds < 90) return `up to about ${Math.max(10, Math.round(seconds / 10) * 10)} seconds`
  return `up to about ${Math.round(seconds / 60)} min`
}

/**
 * Ile dachow wolno przepuscic przez model w jednym zleceniu.
 *
 * Limitow uslugi (500 budynkow, 10 km² na zadanie) nie ma tu wcale i nie przez pomylke: obszar
 * idzie do modelu kawalek po kawalku, a podzial na kawalki mieszczace sie w tych limitach robi
 * backend (`/api/area/plan`). Wiekszy prostokat nie jest wiec „nie do przyjecia", tylko rozpada
 * sie na wiecej kawalkow.
 *
 * Zostaje jedna granica i jest nia czas: przy 40-115 ms na dach 2 000 dachow to od poltorej do
 * czterech minut, co jeszcze da sie przeczekac przy otwartym panelu. 10 631 budynkow z centrum
 * Warszawy to kwadranse i na to nie pozwalamy — lepiej odmowic z liczba w rece niz zajac model
 * na pol godziny zleceniem, ktore nikt nie doczeka do konca.
 */
const MAX_STREAM_ROOFS = 2000

/**
 * Powod, dla ktorego nie zlecamy analizy tego obszaru — albo `null`, gdy zlecamy.
 *
 * Liczba budynkow jest znana z wyniku skanu, wiec powod stoi przy wylaczonym przycisku, zanim
 * padnie klikniecie.
 */
function budgetReason(scan: AreaScan): string | null {
  if (scan.stats.total <= MAX_STREAM_ROOFS) return null
  const max = NUMBER_FORMAT.format(MAX_STREAM_ROOFS)
  return `The model can analyse up to ${max} roofs in one go; this area has ${NUMBER_FORMAT.format(scan.stats.total)}.`
}

/**
 * Linia postepu w trakcie pracy: ktory kawalek idzie teraz i ile dachow model juz ocenil.
 *
 * Numer kawalka liczy sie jako `done + 1`, bo w trakcie pracy nad trzecim kawalkiem wrocily dwa.
 * Dachow nie pokazujemy, dopoki nie ma ani jednej oceny — „0 roofs so far" nie jest informacja.
 */
function progressLabel(progress: AreaAnalysisProgress): string {
  const areas = `Analysing area ${Math.min(progress.done + 1, progress.total)} of ${progress.total}`
  return progress.buildings > 0 ? `${areas} · ${roofsLabel(progress.buildings)} so far` : `${areas}…`
}

/**
 * Zdanie przy niepelnym wyniku — obowiazkowe.
 *
 * Liczby i lista pokazuja sie w trakcie i o to w tym calym strumieniowaniu chodzi, ale czesciowe
 * „120 flagged" bez tego zdania czyta sie jak wynik koncowy calego zaznaczenia, czyli jest
 * klamstwem o tym, ile dachow obejrzano.
 */
function partialNote(progress: AreaAnalysisProgress): string {
  return `These numbers cover ${progress.done} of ${progress.total} areas analysed so far.`
}

/** Wynik jest niepelny, dopoki nie wrocil kazdy kawalek z planu — takze wtedy, gdy przerwal go blad. */
function isPartial(progress: AreaAnalysisProgress | null): progress is AreaAnalysisProgress {
  return progress !== null && progress.done < progress.total
}

/**
 * Fragment zaznaczenia bez swojego kawalka. Model nigdy na niego nie spojrzal, wiec brak
 * pomaranczowych obrysow w tym miejscu nie jest wynikiem — bez tego zdania wygladalby jak wynik.
 */
const SKIPPED_NOTE =
  'Part of this selection is too dense to split into areas the model accepts, so it was skipped: the model never looked at those roofs, and no orange there is not a result.'

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
  progress,
  threshold,
  onThresholdChange,
  onPickBuilding,
}: {
  analysis: AreaAnalysis
  progress: AreaAnalysisProgress | null
  threshold: number | null
  onThresholdChange: (value: number) => void
  onPickBuilding: (id: number) => void
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

      {/* Zdanie o czesci obszaru stoi przy liczbie prowadzacej, nie w przypisach: to ona najbardziej
          klamie, gdy wyglada na policzona z calosci. */}
      {isPartial(progress) ? <p className="mt-2 text-xs text-ink-muted">{partialNote(progress)}</p> : null}

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

      {/* Konkrety pod skala: te same dachy, ktore liczy `suspectedNotListed`, tylko po jednym.
          Wybor idzie tym samym progiem, ktorym policzone sa liczby wyzej (`stats.threshold`),
          wiec suwak skraca i wydluza te liste natychmiast i bez pytania modelu drugi raz. */}
      <FlaggedRoofs
        roofs={selectFlaggedNotListed(analysis, stats.threshold)}
        total={stats.suspectedNotListed}
        onPick={onPickBuilding}
      />
    </div>
  )
}

/**
 * Ocena modelu dla calego obszaru: osobny krok, nie automat po skanie.
 *
 * Obszar idzie do modelu kawalek po kawalku, a liczby i lista pokazuja sie w miare splywania
 * wynikow — dlatego stan pracy i wynik wystepuja tu RAZEM, a nie jeden zamiast drugiego. Przy
 * niepelnym wyniku obok liczb stoi zdanie, jakiej czesci obszaru dotycza.
 *
 * Model liczy minuty, wiec uruchomienie jest decyzja uzytkownika; gdy obszar przekracza budzet
 * czasu, powod stoi przy wylaczonym przycisku, zanim padnie klikniecie.
 */
function ModelSection({
  scan,
  analysis,
  loading,
  error,
  progress,
  skipped,
  onAnalyse,
  threshold,
  onThresholdChange,
  onPickBuilding,
}: {
  scan: AreaScan
  analysis: AreaAnalysis | null
  loading: boolean
  error: string | null
  progress: AreaAnalysisProgress | null
  skipped: boolean
  onAnalyse: () => void
  threshold: number | null
  onThresholdChange: (value: number) => void
  onPickBuilding: (id: number) => void
}) {
  const reason = budgetReason(scan)

  return (
    <Section title="Model analysis">
      {/* Praca idzie minutami; bez tej linii panel wyglada na zepsuty, a przy kilku kawalkach
          sama liczba dachow nie mowilaby, ile z obszaru jest juz za nami. */}
      {loading ? (
        <div className="mb-3">
          <p className="text-ink-muted">
            {progress === null || progress.total === 0
              ? `Analysing ${roofsLabel(scan.stats.total)}…`
              : progressLabel(progress)}
          </p>
          <p className="label-micro mt-1">{waitLabel(scan.stats.total)}</p>
        </div>
      ) : null}

      {/* Blad stoi nad liczbami, bo to on tlumaczy, dlaczego dalszych kawalkow nie bedzie. */}
      {error ? <p className="mb-3 text-listed">{error}</p> : null}

      {skipped ? <p className="mb-3 text-xs text-ink-muted">{SKIPPED_NOTE}</p> : null}

      {analysis ? (
        <ModelNumbers
          analysis={analysis}
          progress={progress}
          threshold={threshold}
          onThresholdChange={onThresholdChange}
          onPickBuilding={onPickBuilding}
        />
      ) : null}

      {/* Przycisk wraca, gdy nic nie idzie i nie ma jeszcze zadnego wyniku: pierwsze uruchomienie
          albo ponowienie po bledzie, ktory przyszedl przed pierwszym kawalkiem. */}
      {!loading && analysis === null ? (
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
        </div>
      ) : null}
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
  analysisProgress,
  analysisSkipped,
  onAnalyse,
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
        progress={analysisProgress}
        skipped={analysisSkipped}
        onAnalyse={onAnalyse}
        threshold={threshold}
        onThresholdChange={onThresholdChange}
        onPickBuilding={onPickBuilding}
      />
    </Shell>
  )
}
