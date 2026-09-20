import type { AreaAnalysis, AreaAnalysisStats, SuspectedRoof } from '../api/client'

/**
 * Liczniki modelu przeliczone dla progu wybranego w interfejsie.
 *
 * Liczymy w przegladarce, bo odpowiedz modelu zawiera ocene KAZDEGO ocenionego budynku osobno
 * (`analysis.buildings`), a tamta instancja przyjmuje 10 zapytan na minute i jedno naraz —
 * ponowne odpytywanie przy kazdym ruchu suwaka byloby nie do utrzymania i przy okazji kazdy ruch
 * kosztowalby kilka sekund czekania.
 *
 * Warunek podejrzenia to `probability >= threshold` — dokladnie ten sam, ktorego uzywa backend
 * (`AnalysedBuilding.suspected` w `app/area_analysis.py`), wiec przy progu domyslnym z odpowiedzi
 * wychodza te same liczby, co przyszly z serwera. Pilnuje tego osobny test.
 *
 * Od progu nie zaleza `analysed`, `noResult`, `modelName` ani `unknownToUs`: brak oceny zostaje
 * brakiem oceny przy kazdym progu, a budynek nieznany naszej bazie nie wchodzi do zadnego
 * licznika. Te pola przechodza z backendu nietkniete.
 */
export function recountStats(analysis: AreaAnalysis, threshold: number): AreaAnalysisStats {
  const { stats } = analysis

  /*
   * Przycieta lista: oddajemy liczby backendu bez zmian.
   *
   * Przy `truncated` w `buildings` nie ma wszystkich ocenionych budynkow, wiec przeliczenie
   * opisywaloby tylko te, ktore przyszly — i to pod etykietami, ktore obiecuja caly obszar.
   * Wybrane wyjscie: nie przeliczac wcale i zostawic prog backendu (`stats.threshold` wraca tu
   * niezmieniony, wiec mapa filtruje tym samym progiem, ktorym policzone sa liczby), a suwak
   * w panelu w tym stanie znika razem ze zdaniem, dlaczego. Alternatywa — przeliczac i dopisac
   * „dotyczy tylko pobranych dachow" — dawala dwie rozne podstawy liczenia w jednej tabelce.
   * Dzis to nie wystepuje: backend oddaje do 100 budynkow, czyli tyle, ile maksymalnie przyjmuje
   * model, ale stan „nie mam pelnej listy" musi byc obsluzony, a nie zalozony jako niemozliwy.
   */
  if (analysis.truncated) return stats

  const suspectedRoofs = analysis.buildings.filter((roof) => roof.probability >= threshold)
  const suspectedListed = suspectedRoofs.filter((roof) => roof.listed).length
  const suspected = suspectedRoofs.length
  const suspectedRoofAreaM2 = suspectedRoofs.reduce((sum, roof) => sum + roof.areaM2, 0)

  return {
    ...stats,
    suspected,
    // Mianownikiem jest `analysed`, nigdy `analysed + noResult`: dach bez oceny jest nieznany,
    // a nie czysty. Ta sama regula stoi w backendzie. Zaokraglenie jak tam: cztery cyfry udzialu.
    suspectedShare: stats.analysed === 0 ? 0 : roundTo(suspected / stats.analysed, 4),
    // Odejmowanie, a nie drugie zliczanie — suma obu skladnikow zawsze jest rowna `suspected`.
    suspectedNotListed: suspected - suspectedListed,
    suspectedListed,
    // Zgloszony bez flagi liczy sie tylko wsrod ocenionych; zgloszony bez oceny nie jest
    // „modelu zdaniem bez pokrycia" i nie ma go na tej liscie.
    listedNotSuspected: analysis.buildings.filter((roof) => roof.listed && roof.probability < threshold).length,
    suspectedRoofAreaM2: roundTo(suspectedRoofAreaM2, 1),
    threshold,
  }
}

/**
 * Dachy na liste „niezgloszone z flaga": ocena od progu w gore i brak w rejestrze, najwyzsza
 * ocena na gorze.
 *
 * Wybor stoi tutaj, a nie w komponencie, bo to dokladnie ten sam warunek progu
 * (`probability >= threshold`), ktorym `recountStats` liczy `suspectedNotListed`. Gdyby filtrowal
 * komponent, warunek istnialby w dwoch miejscach i pierwsza poprawka w jednym rozjechalaby liste
 * z liczba nad nia — a lista, ktora nie zgadza sie z liczba prowadzaca, jest gorsza niz jej brak.
 *
 * Panel podaje tu `threshold` z wyniku `recountStats`, wiec dlugosc tej listy rowna sie
 * `suspectedNotListed`. Jedyny wyjatek to przycieta odpowiedz modelu: tam liczby zostaja
 * backendowe (patrz `recountStats`), a `analysis.buildings` nie zawiera wszystkich ocen, wiec
 * lista jest krotsza od liczby w naglowku i panel mowi to zdaniem pod lista.
 *
 * Kolejnosc malejaca po ocenie, bo pierwszy wiersz to pierwszy dach do obejrzenia. Przy rownych
 * ocenach zostaje kolejnosc z odpowiedzi — `Array#sort` jest stabilny, a `filter` pracuje na
 * kopii, wiec `analysis.buildings` zostaje nietkniete.
 */
export function selectFlaggedNotListed(analysis: AreaAnalysis, threshold: number): SuspectedRoof[] {
  return analysis.buildings
    .filter((roof) => !roof.listed && roof.probability >= threshold)
    .sort((left, right) => right.probability - left.probability)
}

/**
 * Prog, ktory naprawde obowiazuje liczby na ekranie: wybor uzytkownika albo prog z odpowiedzi,
 * gdy nikt suwaka nie ruszal. Przy przycietej liscie zawsze prog backendu, bo tam nie liczymy
 * od nowa. Mapa filtruje tym samym progiem, wiec liczba pomaranczowych obrysow zgadza sie
 * z „niezgloszonymi z flaga" w panelu.
 */
export function effectiveThreshold(analysis: AreaAnalysis, chosen: number | null): number {
  return recountStats(analysis, chosen ?? analysis.stats.threshold).threshold
}

/**
 * Jeden koszyk histogramu ocen: przedzial polotwarty `[from, to)` i liczba dachow w nim.
 *
 * Ostatni koszyk jest domkniety z prawej (`[0,95; 1]`), bo ocena 1 jest ocena i musi byc gdzies
 * policzona — inaczej suma slupkow nie rownalaby sie liczbie ocenionych dachow.
 */
export type ScoreBucket = {
  from: number
  to: number
  count: number
}

/**
 * Dwadziescia koszykow po 0,05.
 *
 * Szerokosc koszyka jest rowna krokowi suwaka (`STEP` w `ThresholdSlider`) i to nie jest zbieg
 * okolicznosci: przy tej samej siatce prog wybrany suwakiem zawsze wypada na granicy koszyka,
 * wiec przemalowanie slupkow dzieli je dokladnie na progu, a nie w poprzek ktoregos slupka.
 */
export const SCORE_BUCKET_COUNT = 20

/**
 * Rozklad ocen modelu: ile dachow trafilo w kazdy koszyk.
 *
 * Czysta funkcja nad samymi ocenami, bo cala trudnosc jest w jednej decyzji: gdzie nalezy ocena
 * stojaca dokladnie na granicy koszyka. Granica nalezy do koszyka, ktory sie od niej ZACZYNA
 * (`[from, to)`), wiec 0,05 jest w koszyku 0,05-0,10, a nie w 0-0,05. Dzieki temu kazda ocena
 * wchodzi do dokladnie jednego koszyka i suma slupkow rowna sie `stats.analysed`.
 *
 * Porownania sa zwykle, bez tolerancji, i to jest bezpieczne, bo granice przechodza przez
 * `roundTo(..., 6)`: 3/20 jest wtedy tym samym doublem co `0.15` wczytane z odpowiedzi modelu.
 * Bez tego zaokraglenia granica wypadalaby na 0,15000000000000002 i ocena „0,15" ladowalaby
 * o koszyk nizej, czyli ponizej swojej wlasnej granicy.
 *
 * Do histogramu ida tylko dachy OCENIONE — `analysis.buildings` innych nie zawiera. Dach bez
 * oceny nie jest tu zerem, nie ma go w zadnym koszyku, i podpis pod wykresem mowi to wprost.
 */
export function scoreHistogram(scores: number[], bucketCount: number = SCORE_BUCKET_COUNT): ScoreBucket[] {
  const width = 1 / bucketCount
  const buckets: ScoreBucket[] = Array.from({ length: bucketCount }, (_, index) => ({
    from: roundTo(index * width, 6),
    to: roundTo((index + 1) * width, 6),
    count: 0,
  }))

  for (const score of scores) {
    buckets[bucketIndex(buckets, score)].count += 1
  }

  return buckets
}

/**
 * Koszyk dla jednej oceny: `>=` na dolnej granicy i `<` na gornej, czyli ta sama regula, ktora
 * w `recountStats` decyduje o podejrzeniu — ocena rowna granicy nalezy do przedzialu powyzej.
 *
 * Oceny 1 nie lapie zaden przedzial polotwarty, wiec domyka ja ostatni koszyk. Ocena spoza 0-1
 * nie ma prawa przyjsc z modelu, ale gdyby przyszla, wpada do skrajnego koszyka zamiast wypasc
 * z sumy: slupki maja sie sumowac do liczby ocen, zawsze.
 */
function bucketIndex(buckets: ScoreBucket[], score: number): number {
  const index = buckets.findIndex((bucket) => score >= bucket.from && score < bucket.to)
  if (index !== -1) return index
  return score < buckets[0].from ? 0 : buckets.length - 1
}

/** Zaokraglenie do zadanej liczby cyfr po kropce — tyle samo, ile zaokragla backend. */
function roundTo(value: number, digits: number): number {
  const scale = 10 ** digits
  return Math.round(value * scale) / scale
}
