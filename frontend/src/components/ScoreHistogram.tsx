import type { ScoreBucket } from '../lib/modelStats'
import { scoreHistogram } from '../lib/modelStats'

type ScoreHistogramProps = {
  /** Oceny dachow OCENIONYCH, 0-1: dokladnie `probability` z `analysis.buildings`. */
  scores: number[]
  /** Prog podejrzenia — ta sama liczba, ktora stoi na suwaku i ktora licza liczniki w panelu. */
  threshold: number
  className?: string
}

const NUMBER_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/**
 * Prog z suwaka jest ulamkiem dziesietnym w double, a granice koszykow licza sie z dzielenia,
 * wiec porownujemy z tolerancja, nie na rowno — tak samo jak `isModelDefault` w `ThresholdSlider`.
 * 1e-9 jest o rzedy wielkosci drobniejsze niz cztery cyfry, ktore oddaje model.
 */
const THRESHOLD_TOLERANCE = 1e-9

/**
 * Podpis, bez ktorego histogram klamie.
 *
 * Dachow bez oceny (`noResult`, u nas kilkanascie procent obszaru) nie ma w zadnym koszyku i nie
 * sa zerem: zero to ocena „model nic nie widzi", a brak oceny to „model nie mial czego ocenic".
 * Bez tego zdania wykres czytaloby sie jako rozklad calego obszaru.
 */
const NO_SCORE_NOTE =
  'Scored roofs only: roofs with no score from the model are not in this chart at all, and no score is not the same as a score of zero.'

/** Jedyna liczba mnoga tego wykresu: 1 roof, kazda inna liczba roofs. */
function roofsLabel(count: number): string {
  return `${NUMBER_FORMAT.format(count)} ${count === 1 ? 'roof' : 'roofs'}`
}

/**
 * Slupek nosi kolor podejrzenia, gdy CALY jego przedzial lezy od progu w gore. Prog rowny dolnej
 * granicy koszyka maluje go juz na pomaranczowo, bo ocena rowna progowi jest podejrzeniem — tak
 * liczy backend i `recountStats`.
 *
 * Koszyk przeciety progiem w srodku zostaje neutralny, a linia progu przechodzi przez niego, wiec
 * widac, ze podzial wypada w jego wnetrzu. Zdarza sie to tylko w dwoch przypadkach: prog
 * z odpowiedzi modelu poza siatka 0,05 (suwak chodzi krokiem rownym szerokosci koszyka, wiec sam
 * tego nie zrobi) i prog rowny 1, ktory odcina sama ocene 1 z domknietego ostatniego koszyka.
 */
function isSuspected(bucket: ScoreBucket, threshold: number): boolean {
  return bucket.from >= threshold - THRESHOLD_TOLERANCE
}

/**
 * Wysokosc slupka jako procent pudelka. Najwyzszy koszyk wypelnia je w calosci, reszta jest
 * proporcjonalna do niego — patrz komentarz o skali pionowej nizej.
 */
function barHeight(count: number, peak: number): string {
  return `${((count / peak) * 100).toFixed(1)}%`
}

/**
 * Rozklad ocen modelu pod torem suwaka progu.
 *
 * Po co: sam suwak jest galka bez kontekstu — przesuniecie na 60% nie mowi, czy odcina dwa dachy,
 * czy dwiescie. Tu widac, gdzie model ma skupisko ocen, gdzie jest niepewny i ile dachow
 * przechodzi przez prog przy jednym kliknieciu w strzalke.
 *
 * OS POZIOMA I SUWAK. Slupki zajmuja dokladnie szerokosc pudelka suwaka (ten sam kontener, zero
 * paddingu), wiec 0 jest na lewej krawedzi, 1 na prawej, a kazdy koszyk ma stala szerokosc 1/N.
 * Natywny `<input type="range">` NIE chodzi po tej samej osi: srodek uchwytu jedzie od polowy
 * jego szerokosci do szerokosci toru minus polowa uchwytu, czyli na Chromium (uchwyt ~16 px)
 * do 8 px do wewnatrz z kazdej strony. W panelu szerokim ~310 px to najwyzej ~2,5% szerokosci,
 * dokladnie zero w srodku skali i najwiecej na koncach. Zgranie co do piksela wymagaloby
 * `appearance: none` i wlasnego uchwytu osobno dla WebKita i Gecko — czego ten suwak swiadomie
 * nie robi, bo caly jego sens jest w tym, ze jest natywny (patrz `ThresholdSlider`).
 *
 * Dlatego linia progu jest zamknieta w pudelku histogramu i nie siega do uchwytu: czyta sie jako
 * granica dwoch kolorow na wykresie, a nie jako wskaznik pozycji galki. Nowego przeklamania nie
 * dodaje, bo samo przemalowanie slupkow — po ktore ten wykres istnieje — stoi w tej samej osi
 * i granica koloru wypada dokladnie tam, gdzie linia.
 *
 * SKALA PIONOWA JEST LINIOWA, najwyzszy slupek wypelnia pudelko. Rozklad ocen ma zwykle duze
 * skupisko przy zerze i to skupisko JEST informacja: wiekszosc dachow nie przypomina falistej
 * plyty. Skala logarytmiczna splaszczylaby ten czubek i rzadkie wysokie oceny wygladalyby na
 * liczniejsze, niz sa — czyli podsuwalaby dokladnie ten odczyt, przed ktorym ostrzega caly panel.
 * Obciecie czubka robi to samo, tylko ciszej. Przy liniowej dwa razy wyzszy slupek to dwa razy
 * wiecej dachow, bez wyjatku, a liczba z czubka stoi wypisana pod wykresem, zeby os pionowa
 * miala jednostke.
 *
 * Jedno odstepstwo, swiadome i nazwane: slupek niepustego koszyka ma co najmniej 1 px
 * (`min-h-px`). Bez tego koszyk z jednym dachem obok skupiska trzystu znika i wyglada na pusty,
 * czyli klamie w druga strone — o zero. Odstepstwo dotyczy tylko wysokosci podpikselowych
 * i nigdy nie zmniejsza zadnego slupka.
 *
 * Kontrolka zostaje jedna i jest nia `<input type="range">`; wykres jest ilustracja, wiec ma
 * `aria-hidden` i ani jednego elementu interaktywnego. Podpis i liczba z czubka zostaja poza
 * `aria-hidden`, bo to zdania do przeczytania, a nie grafika.
 */
export function ScoreHistogram({ scores, threshold, className }: ScoreHistogramProps) {
  // Bez ani jednej oceny nie ma rozkladu, a pusta ramka wygladalaby jak rozklad rowny zeru.
  if (scores.length === 0) return null

  const buckets = scoreHistogram(scores)
  const peak = Math.max(...buckets.map((bucket) => bucket.count))
  // Szerokosc koszyka w procentach, nie w pikselach: podzialka ma byc ta sama przy kazdej
  // szerokosci panelu i wypadac dokladnie tam, gdzie linia progu liczona z tej samej osi.
  const cellWidth = `${(100 / buckets.length).toFixed(4)}%`

  return (
    <div className={className ?? ''}>
      <div
        data-testid="score-histogram"
        aria-hidden="true"
        className="relative flex h-10 items-end border-b border-hairline"
      >
        {buckets.map((bucket) => (
          // Komorka trzyma szerokosc koszyka, slupek w niej wysokosc. Poziomy padding 1 px
          // rozdziela slupki, nie ruszajac podzialki: `box-sizing` liczy go w te same 5%.
          <div
            key={bucket.from}
            data-testid="score-bucket"
            data-from={bucket.from}
            data-count={bucket.count}
            className="flex h-full items-end px-px"
            style={{ width: cellWidth }}
          >
            {bucket.count === 0 ? null : (
              <div
                data-testid="score-bar"
                className={`min-h-px w-full ${isSuspected(bucket, threshold) ? 'bg-suspected' : 'bg-not-listed'}`}
                style={{ height: barHeight(bucket.count, peak) }}
              />
            )}
          </div>
        ))}

        {/* Linia progu w osi wykresu — jedzie razem z suwakiem, bo bierze te sama wartosc. */}
        <span
          data-testid="score-threshold-line"
          className="absolute inset-y-0 w-px bg-ink"
          style={{ left: `${(threshold * 100).toFixed(1)}%` }}
        />
      </div>

      <div className="mt-1 flex items-baseline justify-between gap-4">
        <span className="label-micro">Score distribution</span>
        {/* Os pionowa bez liczby nie ma jednostki, a wtedy „wysoki slupek" nie znaczy nic. */}
        <span className="label-micro">Tallest bar {roofsLabel(peak)}</span>
      </div>

      <p className="mt-1 text-[10px] leading-tight text-ink-faint">{NO_SCORE_NOTE}</p>
    </div>
  )
}
