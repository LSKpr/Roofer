import type { SuspectedRoof } from '../api/client'
import { FlaggedRoofTile } from './FlaggedRoofTile'

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
  /** Ile kafelkow pokazac; reszte opisuje zdanie pod siatka. */
  limit?: number
}

const NUMBER_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/**
 * Gorna dlugosc listy. Dwadziescia piec kafelkow to tyle, ile da sie przejrzec w jednym
 * posiedzeniu; przy 120 pozycjach dluga lista i tak konczy sie przewijaniem bez patrzenia,
 * a liczby nad nia opisuja caly obszar. To jednoczesnie gorna liczba zdjec, o ktore siatka
 * pyta naraz nasz backend.
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
 * Miniatury i ocena pochodza z dwoch roznych zdjec: kadr w siatce jest z ortofotomapy GUGiK,
 * a model ocenial zdjecie Google Satellite z zoomu 20 — inne zrodlo i inny moment. Bez tego
 * zdania ktos porowna ocene z obrazkiem i uzna, ze model sie myli (albo ze ma racje) na
 * podstawie zdjecia, ktorego model nigdy nie widzial.
 */
const IMAGE_SOURCE_NOTE =
  'The thumbnails come from the GUGiK orthophoto and show the roof as it looked during the aerial survey, not the Google Satellite frame at zoom 20 that the model scored.'

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

/**
 * Lista dachow, ktorych nikt nie zglosil, a model cos na nich widzi — wlasciwy produkt tej
 * aplikacji: liczba „120" mowi o skali, a dopiero te kafelki da sie objechac.
 *
 * Siatka miniatur, nie wiersze liczb: dwadziescia piec wycinkow ortofoto obok siebie przekonuje
 * dowodem, a nie grafika — widac, ze pod ocena stoi konkretny dach. Kazdy kafelek niesie swoja
 * ocene i powierzchnie, wiec kadr, ktorego GUGiK nie oddal, nie wypada z listy.
 *
 * Komponent jest czysto prezentacyjny, jak `ThresholdSlider`: dostaje gotowa liste i `onPick`,
 * wiec nie ma wlasnego pojecia o progu ani o tym, co znaczy „podejrzany". Dzieki temu suwak
 * dziala na te liste natychmiast — rodzic przelicza wybor z ocen, ktore juz ma, bez zapytania
 * do modelu (tamta instancja przyjmuje 10 zapytan na minute).
 *
 * Identyfikator OSM stoi pod kafelkiem jako drobny podpis, bo to on jest adresem tego dachu
 * w calej reszcie aplikacji: klik otwiera karte budynku z duzym wycinkiem ortofoto i pelna nota
 * modelu.
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
        <>
          {/* Siatka bywa dluga, wiec przewija sie sama, a liczby modelu zostaja widoczne nad nia.
              Trzy kolumny, bo panel ma 352 px: wychodzi ~100 px na kadr, czyli miniatura. */}
          <ul className="mt-2 grid max-h-72 grid-cols-3 gap-1.5 overflow-y-auto">
            {shown.map((roof) => (
              <li key={roof.id}>
                <FlaggedRoofTile id={roof.id} probability={roof.probability} areaM2={roof.areaM2} onPick={onPick} />
              </li>
            ))}
          </ul>
          {/* Zdanie stoi pod siatka, bo dotyczy tych kadrow: bez niego ocena i obrazek wygladaja
              na jedno zdjecie, a sa z dwoch roznych zrodel i dwoch roznych momentow. */}
          <p className="mt-2 text-xs text-ink-faint">{IMAGE_SOURCE_NOTE}</p>
        </>
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
