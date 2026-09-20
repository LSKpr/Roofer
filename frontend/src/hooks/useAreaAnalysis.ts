import { useCallback, useRef, useState } from 'react'
import {
  fetchAreaAnalysis,
  fetchAreaPlan,
  type AreaAnalysis,
  type AreaPlan,
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

export type AreaAnalysisState = {
  /** Wynik scalony z kawalkow, ktore juz splynely — widoczny takze w trakcie pracy. */
  analysis: AreaAnalysis | null
  loading: boolean
  error: string | null
  /** `null`, dopoki nie ma planu (czyli przed pierwsza odpowiedzia) albo po `clear`. */
  progress: AreaAnalysisProgress | null
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

  const parts: AreaAnalysis[] = []
  for (const chunk of chunks) {
    // Sprawdzenie przed KAZDYM kawalkiem, nie tylko przed pierwszym: `clear` i nowe `run` musza
    // przerwac petle, a nie schowac wynik. Inaczej zamkniety panel zostawia w tle kilka minut
    // zapytan do modelu, ktorych nikt juz nie zobaczy.
    if (!alive()) return
    try {
      parts.push(await fetchAreaAnalysis(chunk))
    } catch (error: unknown) {
      /*
       * Blad jednego kawalka nie wyrzuca dotychczasowej pracy: zostawiamy to, co splynelo,
       * pokazujemy `detail` z backendu i przestajemy pytac dalej. Kilka minut inferencji do kosza
       * z powodu jednego 503 to najgorsze mozliwe zachowanie, a kolejne kawalki najpewniej
       * dostana ten sam blad.
       */
      publish({ error: messageFrom(error), running: false })
      return
    }
    if (!alive()) return
    const merged = mergeAnalyses(parts)
    publish({
      analysis: merged,
      progress: { done: parts.length, total: chunks.length, buildings: merged?.stats.analysed ?? 0 },
    })
  }
  publish({ running: false })
}

/**
 * Ocena modelu dla obszaru, zlecana zdarzeniem — kliknieciem przycisku, nie zmiana propsa.
 *
 * Obszar idzie do modelu **kawalek po kawalku**, a wynik jest publikowany po kazdym kawalku:
 * model liczy 40–115 ms na dach, wiec przy kilkuset dachach jedna odpowiedz na koniec kazalaby
 * patrzec minutami na pusty panel. Podzial robi backend (`/api/area/plan`), bo tylko on zna
 * limity uslugi i liczby budynkow.
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
    setJob({ request: id, analysis: null, error: null, progress: null, skipped: false, running: true })
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
    run,
    clear,
  }
}
