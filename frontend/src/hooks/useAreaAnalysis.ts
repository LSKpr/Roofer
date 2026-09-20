import { useCallback, useRef, useState } from 'react'
import {
  fetchAreaAnalysis,
  fetchAreaPlan,
  type AreaAnalysis,
  type AreaPlan,
  type AreaPlanChunk,
  type Bounds,
  type SuspectedRoof,
} from '../api/client'
import { recountStats } from '../lib/modelStats'

/**
 * Postep analizy kawalek po kawalku.
 *
 * `done` to kawalki, ktore juz wrocily, `total` to dlugosc planu, a `buildings` to dachy ocenione
 * dotad — po deduplikacji, czyli dokladnie ta liczba, ktora stoi w panelu jako „Roofs analysed".
 * Dwie rozne liczby pod jedna nazwa byly by gorsze niz brak postepu.
 */
export type AreaAnalysisProgress = { done: number; total: number; buildings: number }

/**
 * Pusta lista kawalkow, wspolna dla wszystkich stanow bez postepu.
 *
 * Jedna stala, a nie `[]` w kazdym miejscu: ta tablica jest propsem mapy, a nowa tozsamosc przy
 * kazdym renderze kazalaby `MapView` przeliczac zrodlo GeoJSON bez powodu. Nikt jej nie mutuje —
 * kazda zmiana postepu buduje nowa tablice.
 */
const NO_CHUNKS: Bounds[] = []

/** Kawalek planu w prostokat dla mapy: liczba budynkow jest postepem, a nie geometria. */
function chunkBounds(chunk: AreaPlanChunk): Bounds {
  return { sw: chunk.sw, ne: chunk.ne }
}

export type AreaAnalysisState = {
  /** Wynik scalony z kawalkow, ktore juz splynely — widoczny takze w trakcie pracy. */
  analysis: AreaAnalysis | null
  loading: boolean
  error: string | null
  /** `null`, dopoki nie ma planu (czyli przed pierwsza odpowiedzia) albo po `clear`. */
  progress: AreaAnalysisProgress | null
  /**
   * Kawalek, ktory model liczy w tej chwili — po to, zeby mapa mogla pokazac, gdzie model patrzy.
   *
   * `null` znaczy „nic nie leci": przed planem, po ostatnim kawalku, po bledzie i po `clear`.
   * Przy planie z jednym kawalkiem zostaje `null` na cala analize: jeden kawalek jest rowny
   * zaznaczeniu, wiec byla by to druga ramka dokladnie na prostokacie, ktory mapa juz rysuje.
   */
  analysingChunk: Bounds | null
  /**
   * Kawalki, ktore model juz policzyl, w kolejnosci z planu — z nich powstaje efekt przemiatania
   * zaznaczenia. Pusta lista znaczy „nie ma czego pokazywac": tak samo jak przy `analysingChunk`
   * przed planem, po calej analizie, po `clear` i przy planie z jednym kawalkiem.
   *
   * Po BLEDZIE kawalka lista zostaje niepusta, i to jest cala jej wartosc w tym momencie:
   * pokazuje, ile obszaru model obejrzal, zanim przestal odpowiadac.
   */
  analysedChunks: Bounds[]
  /**
   * Plan oddal `truncated`: fragment zaznaczenia byl za gesty na podzial i nie ma swojego kawalka,
   * wiec model nigdy na niego nie spojrzy. Panel musi to powiedziec — brak flag w tym miejscu
   * wyglada inaczej niz „nie patrzylismy tam wcale".
   */
  skipped: boolean
  /** Zleca ocene modelu dla prostokata. Kolejne wywolanie porzuca poprzednie. */
  run: (bounds: Bounds) => void
  clear: () => void
}

/** Stan jednego zlecenia, opisany jego numerem: odpowiedz z innego numeru nic tu nie zmienia. */
type Job = {
  request: number
  analysis: AreaAnalysis | null
  error: string | null
  progress: AreaAnalysisProgress | null
  skipped: boolean
  /** Petla po kawalkach nadal chodzi. Nie da sie tego wyliczyc z wyniku, bo wynik jest czesciowy. */
  running: boolean
  analysingChunk: Bounds | null
  analysedChunks: Bounds[]
}

/** Zmiana stanu zlecenia: tylko te pola, ktore naprawde sie zmienily. */
type Patch = Partial<Omit<Job, 'request'>>

/**
 * Wyniki kawalkow w jeden wynik obszaru.
 *
 * **Deduplikacja po `id` jest obowiazkowa.** Budynek stojacy na linii ciecia wraca w dwoch
 * kawalkach (12 z 703 ocen w prostokacie testowym, ~1,7%). Bez deduplikacji policzylby sie dwa
 * razy w kazdej statystyce i stanalby dwa razy na liscie dachow do objazdu. Pierwsza ocena wygrywa:
 * to ten sam model na tym samym zdjeciu, wiec druga nie wnosi nic poza duplikatem.
 *
 * Liczniki zalezne od progu (`suspected`, `suspectedShare`, powierzchnia, oba rozbicia po rejestrze)
 * liczy `recountStats` z odduplikowanej listy — ten sam modul, ktorym panel przelicza je przy ruchu
 * suwaka, wiec warunek progu zostaje w jednym miejscu i scalony wynik ma te same zaokraglenia,
 * co odpowiedz backendu dla jednego kawalka.
 *
 * `threshold` i `modelName` bierzemy z pierwszego kawalka: kazdy kawalek idzie do tej samej uslugi
 * i tego samego modelu, wiec sa identyczne, a sumowanie albo srednia nie mialyby sensu.
 */
export function mergeAnalyses(parts: AreaAnalysis[]): AreaAnalysis | null {
  const first = parts[0]
  if (first === undefined) return null

  const byId = new Map<number, SuspectedRoof>()
  for (const part of parts) {
    for (const roof of part.buildings) {
      if (!byId.has(roof.id)) byId.set(roof.id, roof)
    }
  }
  const buildings = [...byId.values()]

  const merged: AreaAnalysis = {
    stats: {
      ...first.stats,
      // Odduplikowane oceny, nie suma `analysed` z kawalkow: ta suma liczylaby granice dwa razy.
      analysed: buildings.length,
      /*
       * TU SCALANIE JEST PRZYBLIZONE, i to jedyne takie miejsce.
       *
       * `noResult` sumujemy po kawalkach, bo backend nie oddaje identyfikatorow dachow bez oceny —
       * nie ma czego deduplikowac. Dach bez oceny stojacy dokladnie na linii ciecia policzy sie
       * wiec dwa razy. Przy ~1,7% budynkow na granicach (12 z 703 w prostokacie testowym) to nie
       * zmienia obrazu obszaru, ale musi byc jawne, a nie ukryte w kodzie bez komentarza.
       */
      noResult: parts.reduce((sum, part) => sum + part.stats.noResult, 0),
      // Poza wszystkimi licznikami, wiec sumujemy wprost. Zero znaczy „snapshoty sie zgadzaja".
      unknownToUs: parts.reduce((sum, part) => sum + (part.stats.unknownToUs ?? 0), 0),
    },
    buildings,
    // Przycieta odpowiedz choc jednego kawalka przycina caly wynik: nie mamy wtedy wszystkich ocen.
    truncated: parts.some((part) => part.truncated),
  }

  /*
   * `recountStats` przy `truncated` oddaje liczby backendu bez zmian (nie ma z czego przeliczac),
   * a tu przeliczyc trzeba, bo liczby z jednego kawalka nie opisuja obszaru. Dlatego liczymy jak
   * z pelnej listy, a `truncated` z kawalkow jedzie dalej w wyniku i panel gasi przez nie suwak.
   * Dzis to nie wystepuje: kazdy kawalek planu miesci sie w bramce, a backend przycina liste
   * dokladnie na limicie bramki — ale gdyby wystapilo, `analysed` opisywaloby oceny, ktore dotarly.
   */
  return { ...merged, stats: recountStats({ ...merged, truncated: false }, first.stats.threshold) }
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : 'Could not analyse the area.'
}

/**
 * Plan, a potem kawalki po kolei.
 *
 * Kawalki ida **w kolejnosci z planu** i **jeden po drugim**. Kolejnosc z planu jest przestrzennie
 * zwarta (zachod przed wschodem, poludnie przed polnoca), wiec sasiadujace prostokaty trafiaja
 * w cache kafli uslugi — przetasowanie ich albo wyslanie rownolegle kosztowaloby kafle drugi raz,
 * a tamta usluga i tak liczy jedno zadanie naraz.
 *
 * Prostokaty kawalkow ida osobno do stanu (`analysingChunk`, `analysedChunks`), bo sam licznik
 * „3 z 7" nie mowi, KTOREGO fragmentu dotyczy — a to jest jedyna rzecz, ktora na mapie widac.
 */
async function streamChunks(bounds: Bounds, alive: () => boolean, publish: (patch: Patch) => void): Promise<void> {
  let plan: AreaPlan
  try {
    plan = await fetchAreaPlan(bounds)
  } catch (error: unknown) {
    publish({ error: messageFrom(error), running: false })
    return
  }
  if (!alive()) return

  const chunks = plan.chunks
  publish({ progress: { done: 0, total: chunks.length, buildings: 0 }, skipped: plan.truncated })

  /*
   * Podzial pokazujemy tylko wtedy, gdy naprawde jest podzialem. Jeden kawalek jest rowny calemu
   * zaznaczeniu, wiec jego ramka lezalaby dokladnie na prostokacie zeskanowanego obszaru, ktory
   * mapa juz rysuje — druga ramka na tym samym miejscu to szum, nie informacja.
   */
  const split = chunks.length > 1

  const parts: AreaAnalysis[] = []
  const analysed: Bounds[] = []
  for (const chunk of chunks) {
    // Sprawdzenie przed KAZDYM kawalkiem, nie tylko przed pierwszym: `clear` i nowe `run` musza
    // przerwac petle, a nie schowac wynik. Inaczej zamkniety panel zostawia w tle kilka minut
    // zapytan do modelu, ktorych nikt juz nie zobaczy.
    if (!alive()) return
    // Kawalek wchodzi do stanu PRZED zapytaniem: to jedyny moment, w ktorym mapa moze powiedziec,
    // gdzie model patrzy teraz — odpowiedz przyjdzie kilkanascie sekund pozniej.
    if (split) publish({ analysingChunk: chunkBounds(chunk) })
    try {
      parts.push(await fetchAreaAnalysis(chunk))
    } catch (error: unknown) {
      /*
       * Blad jednego kawalka nie wyrzuca dotychczasowej pracy: zostawiamy to, co splynelo,
       * pokazujemy `detail` z backendu i przestajemy pytac dalej. Kilka minut inferencji do kosza
       * z powodu jednego 503 to najgorsze mozliwe zachowanie, a kolejne kawalki najpewniej
       * dostana ten sam blad.
       *
       * Policzone kawalki zostaja na mapie, gasnie sam kawalek, ktory nie wrocil: po bledzie to
       * wlasnie one mowia, ile obszaru model obejrzal, zanim przestal odpowiadac.
       */
      publish({ error: messageFrom(error), running: false, analysingChunk: null })
      return
    }
    if (!alive()) return
    analysed.push(chunkBounds(chunk))
    const merged = mergeAnalyses(parts)
    publish({
      analysis: merged,
      progress: { done: parts.length, total: chunks.length, buildings: merged?.stats.analysed ?? 0 },
      // Nowa tablica, nie ta sama z dopisanym elementem: `MapView` porownuje props przez tozsamosc.
      analysedChunks: split ? [...analysed] : NO_CHUNKS,
    })
  }
  /*
   * Caly obszar policzony: nie ma „aktualnego" kawalka, a policzone przestaja byc informacja —
   * skoro wrocily wszystkie, „ktore juz policzono" znaczy „cale zaznaczenie". Zostaje sam wynik.
   */
  publish({ running: false, analysingChunk: null, analysedChunks: NO_CHUNKS })
}

/**
 * Ocena modelu dla obszaru, zlecana zdarzeniem — kliknieciem przycisku, nie zmiana propsa.
 *
 * Obszar idzie do modelu **kawalek po kawalku**, a wynik jest publikowany po kazdym kawalku:
 * model liczy 40–115 ms na dach, wiec przy kilkuset dachach jedna odpowiedz na koniec kazalaby
 * patrzec minutami na pusty panel. Podzial robi backend (`/api/area/plan`), bo tylko on zna
 * limity uslugi i liczby budynkow.
 *
 * Razem z wynikiem hook wystawia geometrie podzialu: `analysingChunk` (fragment u modelu teraz)
 * i `analysedChunks` (fragmenty, ktore wrocily). Postep liczbowy mowi „3 z 7", ale nie mowi,
 * gdzie te trzy sa — a minuta pracy bez tego wyglada na zawieszona.
 *
 * Numer zlecenia siedzi w `useRef` i jest sprawdzany przed kazdym kawalkiem — po to, zeby
 * porzucone zlecenie naprawde przestalo pytac model, a nie tylko schowalo wynik. Wyscig jest tu
 * realny i dlugi: uzytkownik zdazy zamknac panel albo zaznaczyc drugi obszar w trakcie kwadransa
 * inferencji, a wynik z poprzedniego prostokata opisywalby budynki, ktorych na ekranie juz nie ma.
 */
export function useAreaAnalysis(): AreaAnalysisState {
  const [job, setJob] = useState<Job | null>(null)
  // Numer zlecenia, ktorego wyniki wolno jeszcze przyjac. `clear` podbija go, zeby przerwac petle.
  const latest = useRef(0)

  const run = useCallback((bounds: Bounds) => {
    const id = latest.current + 1
    latest.current = id
    setJob({
      request: id,
      analysis: null,
      error: null,
      progress: null,
      skipped: false,
      running: true,
      analysingChunk: null,
      analysedChunks: NO_CHUNKS,
    })
    // Podwojny straznik: `alive` wstrzymuje dalsze zapytania, a warunek w aktualizatorze pilnuje,
    // zeby spozniona odpowiedz nie dopisala sie do stanu nowszego zlecenia.
    const alive = () => latest.current === id
    const publish = (patch: Patch) => {
      if (!alive()) return
      setJob((previous) => (previous !== null && previous.request === id ? { ...previous, ...patch } : previous))
    }
    void streamChunks(bounds, alive, publish)
  }, [])

  const clear = useCallback(() => {
    latest.current += 1
    setJob(null)
  }, [])

  return {
    analysis: job?.analysis ?? null,
    loading: job?.running ?? false,
    error: job?.error ?? null,
    progress: job?.progress ?? null,
    skipped: job?.skipped ?? false,
    analysingChunk: job?.analysingChunk ?? null,
    analysedChunks: job?.analysedChunks ?? NO_CHUNKS,
    run,
    clear,
  }
}
