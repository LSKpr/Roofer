import type { SuspectedRoof } from '../api/client'

type FlaggedRoofsProps = {
  /**
   * Dachy gotowe do pokazania: juz przefiltrowane progiem i posortowane malejaco po ocenie.
   * Komponent nie zna progu i niczego nie wybiera — robi to `selectFlaggedNotListed`, zeby
   * warunek progu zyl w jednym miejscu razem z licznikami.
   */
  roofs: SuspectedRoof[]
  /**
   * Ile dachow spelnia ten warunek w calym obszarze. Osobno od `roofs.length`, bo widoczna lista
   * bywa krotsza: przez nasz limit dlugosci albo przez przyciecie odpowiedzi modelu. W naglowku
   * stoi ta liczba, bo to ona jest liczba prowadzaca sekcji modelu.
   */
  total: number
  onPick: (id: number) => void
  /** Ile wierszy pokazac; reszte opisuje zdanie pod lista. */
  limit?: number
}

const NUMBER_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/**
 * Gorna dlugosc listy. Dwadziescia piec wierszy to tyle, ile da sie przejrzec w jednym
 * posiedzeniu; przy 120 pozycjach dluga lista i tak konczy sie przewijaniem bez czytania,
 * a liczby nad nia opisuja caly obszar.
 */
const ROW_LIMIT = 25

/** Ta sama fraza podpisuje liczbe prowadzaca sekcji modelu: lista i liczba mowia o tym samym. */
const HEADING = 'Not in the register, flagged by the model'

/**
 * Do czego ta lista sluzy i czego nie dowodzi. Skutecznosc podana przez autora modelu stoi tu
 * drugi raz, mimo ze jest juz nad liczbami: pojedynczy wiersz z ocena „91%" czyta sie jak
 * pewnosc, a nie jak wynik klasyfikatora o czulosci 63%.
 */
const SCORE_NOTE =
  'Roofs to check on site, sorted by score. The model only compares how the covering looks on a satellite photo, and it reports 77% accuracy and 63% asbestos recall — at this threshold some of these roofs will not have asbestos cement on them.'

/**
 * Brak w rejestrze nie jest zarzutem. Bez tego zdania lista czyta sie jak wykaz uchybien, a jest
 * tylko zestawieniem dwoch rzeczy: nikt tego budynku nie zglosil i model cos widzi na zdjeciu.
 */
const REGISTER_NOTE =
  'Missing from the register means nobody reported this building — not that anything is unlawful, and not that the owner failed to report it. The register is incomplete, and a report that does exist may have covered something other than the roof.'

/** Najkrotsze zdanie tej sekcji i najwazniejsze: lista jest zadaniem, nie ustaleniem. */
const FIELD_NOTE = 'This is a list to check on site, not a list of findings.'

/**
 * Pusta lista jest stanem progu, a nie werdyktem o obszarze — sama pustka wygladalaby jak
 * „nic tu nie ma", wiec mowimy to zdaniem i podpowiadamy, co zrobic.
 */
const EMPTY_NOTE =
  'No roof here is both above the threshold and missing from the register. Lower the threshold to see roofs the model scored lower.'

/**
 * Lista ma wlasna gorna dlugosc, a odpowiedz modelu bywa przycieta. W obu przypadkach widac mniej
 * wierszy, niz mowi liczba w naglowku, i to zdanie jest jedynym miejscem, gdzie to przyznajemy.
 */
function truncationNote(shown: number, total: number): string {
  const counts = `${NUMBER_FORMAT.format(shown)} of ${NUMBER_FORMAT.format(total)}`
  return `The list is truncated: showing ${counts} roofs — the numbers above cover the whole area.`
}

/** Ocena przychodzi jako ulamek 0–1; w wierszu czyta sie ja jako liczbe calkowita procent. */
function scoreLabel(probability: number): string {
  return `${Math.round(probability * 100)}%`
}

function areaLabel(squareMeters: number): string {
  return `${NUMBER_FORMAT.format(squareMeters)} m²`
}

/**
 * Lista dachow, ktorych nikt nie zglosil, a model cos na nich widzi — wlasciwy produkt tej
 * aplikacji: liczba „120" mowi o skali, a dopiero te wiersze da sie objechac.
 *
 * Komponent jest czysto prezentacyjny, jak `ThresholdSlider`: dostaje gotowa liste i `onPick`,
 * wiec nie ma wlasnego pojecia o progu ani o tym, co znaczy „podejrzany". Dzieki temu suwak
 * dziala na te liste natychmiast — rodzic przelicza wybor z ocen, ktore juz ma, bez zapytania
 * do modelu (tamta instancja przyjmuje 10 zapytan na minute).
 *
 * Identyfikator OSM stoi w wierszu jako drobny podpis, bo to on jest adresem tego dachu w calej
 * reszcie aplikacji: klik otwiera karte budynku z wycinkiem ortofoto i pelna nota modelu.
 */
export function FlaggedRoofs({ roofs, total, onPick, limit = ROW_LIMIT }: FlaggedRoofsProps) {
  const shown = roofs.slice(0, limit)

  return (
    <section data-testid="flagged-roofs" className="mt-4 border-t border-hairline pt-4">
      {/* Liczba w naglowku jest liczba prowadzaca, nie dlugoscia widocznej listy. */}
      <h3 className="label-micro">{`${HEADING} (${NUMBER_FORMAT.format(total)})`}</h3>
      <p className="mt-1.5 text-xs text-ink-faint">{SCORE_NOTE}</p>

      {shown.length === 0 ? (
        <p className="mt-2 text-ink-muted">{EMPTY_NOTE}</p>
      ) : (
        // Lista bywa dluga, wiec przewija sie sama, a liczby modelu zostaja widoczne nad nia.
        <ul className="mt-2 max-h-56 overflow-y-auto">
          {shown.map((roof) => (
            <li key={roof.id} className="border-t border-hairline first:border-t-0">
              {/* Klikalny jest caly wiersz, nie tekst w nim: celem jest ten dach, nie jego numer. */}
              <button
                type="button"
                onClick={() => onPick(roof.id)}
                className="flex w-full items-center justify-between gap-4 py-2 text-left hover:bg-surface-muted"
              >
                <span className="flex shrink-0 items-center gap-2">
                  {/* Ten sam pomaranczowy token, ktorym mapa maluje obrys tego dachu. */}
                  <span
                    data-testid="flagged-roof-dot"
                    className="inline-block h-2 w-2 shrink-0 bg-suspected"
                    aria-hidden="true"
                  />
                  {/* Ocena wyrozniona, bo to ona ustawia kolejnosc: gora listy to pierwszy wyjazd. */}
                  <span className="font-display text-base leading-none text-ink">{scoreLabel(roof.probability)}</span>
                  <span className="text-ink-muted">{areaLabel(roof.areaM2)}</span>
                </span>
                {/* Identyfikator jest podpisem, nie trescia wiersza, wiec stoi cicho przy krawedzi. */}
                <span className="label-micro min-w-0 truncate">OSM {roof.id}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {shown.length < total ? (
        <p className="mt-3 text-xs text-ink-faint">{truncationNote(shown.length, total)}</p>
      ) : null}

      {/* Te dwa zdania nie znikaja razem z lista: dotycza calej sekcji, nie pojedynczych wierszy. */}
      <div className="mt-3 space-y-1 text-xs text-ink-faint">
        <p>{REGISTER_NOTE}</p>
        <p>{FIELD_NOTE}</p>
      </div>
    </section>
  )
}
