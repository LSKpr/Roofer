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

/** Zaokraglenie do zadanej liczby cyfr po kropce — tyle samo, ile zaokragla backend. */
function roundTo(value: number, digits: number): number {
  const scale = 10 ** digits
  return Math.round(value * scale) / scale
}
