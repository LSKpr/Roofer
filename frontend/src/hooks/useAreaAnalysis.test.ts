import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { mergeAnalyses, useAreaAnalysis } from './useAreaAnalysis'
import type { AreaAnalysis, AreaAnalysisStats, AreaPlan, Bounds, SuspectedRoof } from '../api/client'

const BOUNDS: Bounds = { ne: { lng: 21.61, lat: 51.37 }, sw: { lng: 21.58, lat: 51.35 } }
const OTHER_BOUNDS: Bounds = { ne: { lng: 20.99, lat: 52.24 }, sw: { lng: 20.96, lat: 52.22 } }

/** Prawdziwy podzial prostokata z 691 budynkami pod Zwoleniem: dwa kawalki, 406 i 297 budynkow. */
function aPlan(overrides: Partial<AreaPlan> = {}): AreaPlan {
  return {
    chunks: [
      { sw: { lng: 21.5745, lat: 51.3555 }, ne: { lng: 21.5805, lat: 51.3629 }, buildings: 406 },
      { sw: { lng: 21.5805, lat: 51.3555 }, ne: { lng: 21.5865, lat: 51.3629 }, buildings: 297 },
    ],
    buildings: 691,
    areaKm2: 0.686,
    truncated: false,
    ...overrides,
  }
}

function aRoof(overrides: Partial<SuspectedRoof> = {}): SuspectedRoof {
  return {
    id: 27469148,
    probability: 0.72,
    listed: false,
    areaM2: 163,
    geometry: {
      type: 'Polygon',
      coordinates: [[[21.59, 51.36], [21.591, 51.36], [21.591, 51.361], [21.59, 51.36]]],
    },
    ...overrides,
  }
}

/** Liczby z prawdziwego przebiegu: 74 budynki pod Zwoleniem, 64 z ocena. */
function anAnalysis(overrides: Partial<AreaAnalysis> = {}): AreaAnalysis {
  return {
    stats: {
      analysed: 64,
      noResult: 10,
      suspected: 16,
      suspectedShare: 0.25,
      suspectedNotListed: 14,
      suspectedListed: 2,
      listedNotSuspected: 1,
      suspectedRoofAreaM2: 2431.5,
      threshold: 0.5,
      modelName: '70b702',
    },
    buildings: [aRoof()],
    truncated: false,
    ...overrides,
  }
}

/**
 * Kawalek zlozony z podanych ocen, ze statystykami policzonymi tak, jak policzylby je backend:
 * scalanie ma byc sprawdzalne liczba po liczbie, a nie wobec liczb wpisanych z palca.
 */
function aChunkResult(roofs: SuspectedRoof[], noResult: number, overrides: Partial<AreaAnalysisStats> = {}): AreaAnalysis {
  const flagged = roofs.filter((roof) => roof.probability >= 0.5)
  const listedFlagged = flagged.filter((roof) => roof.listed).length
  return {
    stats: {
      analysed: roofs.length,
      noResult,
      suspected: flagged.length,
      suspectedShare: roofs.length === 0 ? 0 : flagged.length / roofs.length,
      suspectedNotListed: flagged.length - listedFlagged,
      suspectedListed: listedFlagged,
      listedNotSuspected: roofs.filter((roof) => roof.listed && roof.probability < 0.5).length,
      suspectedRoofAreaM2: flagged.reduce((sum, roof) => sum + roof.areaM2, 0),
      threshold: 0.5,
      modelName: '70b702',
      ...overrides,
    },
    buildings: roofs,
    truncated: false,
  }
}

type Response = { status: number; json: () => Promise<unknown> }

/**
 * Odpowiedzi rozwiazywane recznie: kazde wywolanie fetch odklada swoj `resolve` do kolejki, wiec
 * test decyduje, ktora odpowiedz wraca i kiedy. Inaczej nie da sie sprawdzic ani kolejnosci
 * kawalkow, ani wyniku czesciowego, ani porzucenia zlecenia w polowie pracy.
 */
function queuedFetch() {
  const queue: ((response: Response) => void)[] = []
  const stub = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>((resolve) => queue.push(resolve)))
  vi.stubGlobal('fetch', stub)
  return {
    calls: stub,
    urls: () => stub.mock.calls.map((call) => String(call[0])),
    /** Prostokaty, o ktore poszlo pytanie do modelu, w kolejnosci wyslania. */
    analysed: () =>
      stub.mock.calls
        .filter((call) => String(call[0]).includes('/api/area/analyze'))
        .map((call) => JSON.parse(String(call[1]?.body)) as { sw: { lng: number } }),
    async answer(index: number, body: unknown) {
      await act(async () => queue[index]({ status: 200, json: async () => body }))
    },
    async reject(index: number, status: number, detail: string) {
      await act(async () => queue[index]({ status, json: async () => ({ detail }) }))
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// Model ma twarde limity i liczy kilka sekund, wiec analiza jest osobnym krokiem: sam wynik
// skanu nie ma prawa jej wywolac.
it('nie pyta ani o plan, ani o model, dopoki nikt nie zlecil analizy', () => {
  const fetchStub = vi.fn()
  vi.stubGlobal('fetch', fetchStub)

  const { result } = renderHook(() => useAreaAnalysis())

  expect(result.current).toMatchObject({ analysis: null, loading: false, error: null, progress: null })
  expect(fetchStub).not.toHaveBeenCalled()
})

// Plan idzie raz, na cale zaznaczenie; kawalki dopiero po nim i dopiero z niego.
it('pyta najpierw o plan, a dopiero potem o pierwszy kawalek', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))

  expect(result.current.loading).toBe(true)
  expect(backend.urls()).toEqual(['/api/area/plan'])
  expect(backend.calls.mock.calls[0][1]?.body).toBe(JSON.stringify(BOUNDS))

  await backend.answer(0, aPlan())

  expect(backend.urls()).toEqual(['/api/area/plan', '/api/area/analyze'])
  expect(backend.urls().filter((url) => url.includes('/plan'))).toHaveLength(1)
})

// Model liczy jedno zadanie naraz, a kolejnosc z planu jest przestrzennie zwarta (trafia w cache
// kafli uslugi) — wiec kawalki ida po kolei i dopiero po odpowiedzi poprzedniego.
it('nie wysyla drugiego kawalka, dopoki nie wrocil pierwszy, i trzyma kolejnosc z planu', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())

  expect(backend.analysed()).toHaveLength(1)
  expect(backend.analysed()[0].sw.lng).toBe(21.5745)

  await backend.answer(1, anAnalysis())

  expect(backend.analysed()).toHaveLength(2)
  expect(backend.analysed()[1].sw.lng).toBe(21.5805)
})

// Caly sens tej zmiany: liczby i lista sa widoczne, zanim skonczy sie caly obszar.
it('publikuje wynik czesciowy juz po pierwszym kawalku', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  await backend.answer(1, aChunkResult([aRoof({ id: 1 }), aRoof({ id: 2, probability: 0.2 })], 3))

  expect(result.current.analysis?.buildings.map((roof) => roof.id)).toEqual([1, 2])
  expect(result.current.analysis?.stats.analysed).toBe(2)
  // Praca trwa: drugi kawalek jest w drodze, wiec panel nadal ma prawo mowic „w toku".
  expect(result.current.loading).toBe(true)
  expect(result.current.error).toBeNull()
})

// Budynek na linii ciecia wraca w dwoch kawalkach (12 z 703 ocen w prostokacie testowym). Bez
// deduplikacji liczylby sie dwa razy w kazdej statystyce i stal dwa razy na liscie do objazdu.
it('liczy budynek z dwoch kawalkow raz, po deduplikacji po id', async () => {
  const backend = queuedFetch()
  const onTheSeam = aRoof({ id: 500, probability: 0.9, areaM2: 200 })
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  await backend.answer(1, aChunkResult([aRoof({ id: 1 }), onTheSeam], 0))
  await backend.answer(2, aChunkResult([onTheSeam, aRoof({ id: 2, probability: 0.8, areaM2: 100 })], 0))

  const analysis = result.current.analysis
  expect(analysis?.buildings.map((roof) => roof.id)).toEqual([1, 500, 2])
  expect(analysis?.stats.analysed).toBe(3)
  expect(analysis?.stats.suspected).toBe(3)
  expect(analysis?.stats.suspectedNotListed).toBe(3)
  // 163 + 200 + 100, a nie 163 + 200 + 200 + 100.
  expect(analysis?.stats.suspectedRoofAreaM2).toBe(463)
})

it('po scaleniu `analysed` rowna sie liczbie odduplikowanych ocen', async () => {
  const backend = queuedFetch()
  const shared = aRoof({ id: 7, probability: 0.6 })
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  await backend.answer(1, aChunkResult([aRoof({ id: 5 }), aRoof({ id: 6 }), shared], 4))
  await backend.answer(2, aChunkResult([shared, aRoof({ id: 8 })], 2))

  // Suma `analysed` kawalkow to 5, ale unikalnych ocen jest 4.
  expect(result.current.analysis?.stats.analysed).toBe(4)
  expect(result.current.analysis?.buildings).toHaveLength(4)
  // `noResult` sumujemy, bo backend nie oddaje identyfikatorow dachow bez oceny — patrz komentarz
  // w `mergeAnalyses`. To jedyne miejsce, w ktorym scalanie jest przyblizone.
  expect(result.current.analysis?.stats.noResult).toBe(6)
})

it('bierze prog i nazwe modelu z pierwszego kawalka, a `unknownToUs` sumuje', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  await backend.answer(1, aChunkResult([aRoof({ id: 1 })], 0, { unknownToUs: 1 }))
  await backend.answer(2, aChunkResult([aRoof({ id: 2 })], 0, { unknownToUs: 2 }))

  expect(result.current.analysis?.stats.threshold).toBe(0.5)
  expect(result.current.analysis?.stats.modelName).toBe('70b702')
  expect(result.current.analysis?.stats.unknownToUs).toBe(3)
})

it('gasi loading dopiero po ostatnim kawalku i podaje pelny postep', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  expect(result.current.progress).toBeNull()

  await backend.answer(0, aPlan())
  expect(result.current.progress).toEqual({ done: 0, total: 2, buildings: 0 })

  await backend.answer(1, aChunkResult([aRoof({ id: 1 }), aRoof({ id: 2 })], 0))
  expect(result.current.progress).toEqual({ done: 1, total: 2, buildings: 2 })
  expect(result.current.loading).toBe(true)

  await backend.answer(2, aChunkResult([aRoof({ id: 3 })], 0))
  expect(result.current.progress).toEqual({ done: 2, total: 2, buildings: 3 })
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()
})

// Plan mowi, ze fragment zaznaczenia byl za gesty i nie ma swojego kawalka — panel musi to
// powiedziec, bo brak flag w tym miejscu wyglada inaczej niz „nie patrzylismy tam wcale".
it('podaje dalej, ze plan pominal czesc zaznaczenia', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  expect(result.current.skipped).toBe(false)

  await backend.answer(0, aPlan({ truncated: true }))

  expect(result.current.skipped).toBe(true)

  act(() => result.current.clear())
  expect(result.current.skipped).toBe(false)
})

it('zamienia blad planu na komunikat, nie na wyjatek, i nie pyta modelu', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.reject(0, 503, 'The database is not responding.')

  expect(result.current.error).toBe('The database is not responding.')
  expect(result.current.analysis).toBeNull()
  expect(result.current.loading).toBe(false)
  expect(backend.analysed()).toHaveLength(0)
})

// Kilka minut inferencji wyrzucone do kosza z powodu jednego 503 to najgorsze mozliwe zachowanie.
it('zostawia dotychczasowe budynki, gdy kawalek padnie, i przestaje pytac dalej', async () => {
  const backend = queuedFetch()
  const threeChunks = aPlan({ chunks: [...aPlan().chunks, { ...aPlan().chunks[0], buildings: 88 }] })
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, threeChunks)
  await backend.answer(1, aChunkResult([aRoof({ id: 1 }), aRoof({ id: 2 })], 1))
  await backend.reject(2, 503, 'The model is not responding.')

  expect(result.current.error).toBe('The model is not responding.')
  expect(result.current.analysis?.buildings.map((roof) => roof.id)).toEqual([1, 2])
  expect(result.current.analysis?.stats.analysed).toBe(2)
  expect(result.current.loading).toBe(false)
  // Postep zostaje na tym, co naprawde splynelo — panel ma z czego powiedziec „1 z 3".
  expect(result.current.progress).toEqual({ done: 1, total: 3, buildings: 2 })
  // Trzeci kawalek juz nie idzie do sieci, mimo ze plan go mial.
  expect(backend.urls()).toEqual(['/api/area/plan', '/api/area/analyze', '/api/area/analyze'])
})

// Porzucenie musi przerwac petle, a nie tylko schowac wynik: inaczej zamkniety panel zostawia
// w tle kilka minut zapytan do modelu.
it('clear w trakcie przerywa petle, wiec kolejny kawalek nie idzie do sieci', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  expect(backend.analysed()).toHaveLength(1)

  act(() => result.current.clear())
  expect(result.current.loading).toBe(false)
  expect(result.current.analysis).toBeNull()
  expect(result.current.progress).toBeNull()

  // Odpowiedz pierwszego kawalka przychodzi po porzuceniu: nie wraca na ekran i nie rusza dalej.
  await backend.answer(1, anAnalysis())

  expect(result.current.analysis).toBeNull()
  expect(result.current.loading).toBe(false)
  expect(backend.analysed()).toHaveLength(1)
})

it('nowe run porzuca poprzednie zlecenie w polowie planu', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  act(() => result.current.run(OTHER_BOUNDS))

  // Nowe zlecenie zaczyna od wlasnego planu, a nie od kawalkow poprzedniego.
  expect(backend.urls()).toEqual(['/api/area/plan', '/api/area/analyze', '/api/area/plan'])
  expect(backend.calls.mock.calls[2][1]?.body).toBe(JSON.stringify(OTHER_BOUNDS))

  // Spozniony kawalek porzuconego obszaru nie dopisuje sie do nowego wyniku i nie ciagnie petli.
  await backend.answer(1, aChunkResult([aRoof({ id: 999 })], 0))
  expect(result.current.analysis).toBeNull()

  await backend.answer(2, aPlan({ chunks: [aPlan().chunks[0]] }))
  await backend.answer(3, aChunkResult([aRoof({ id: 1 })], 0))

  expect(result.current.analysis?.buildings.map((roof) => roof.id)).toEqual([1])
  expect(result.current.loading).toBe(false)
})

it('clear czysci wynik, blad i postep', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan({ chunks: [aPlan().chunks[0]] }))
  await backend.answer(1, anAnalysis())
  expect(result.current.analysis).not.toBeNull()

  act(() => result.current.clear())

  expect(result.current).toMatchObject({ analysis: null, loading: false, error: null, progress: null })

  act(() => result.current.run(BOUNDS))
  await backend.reject(2, 503, 'The model is not responding.')
  expect(result.current.error).toBe('The model is not responding.')

  act(() => result.current.clear())
  expect(result.current.error).toBeNull()
})

// Plan bez kawalkow (cale zaznaczenie za geste na podzial) nie ma czego pytac, ale tez nie jest
// bledem: konczy sie postojem z wlasnym postepem, a nie zawieszonym „w toku".
it('konczy bez wyniku, gdy plan nie oddal ani jednego kawalka', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan({ chunks: [], truncated: true }))

  expect(result.current.loading).toBe(false)
  expect(result.current.analysis).toBeNull()
  expect(result.current.progress).toEqual({ done: 0, total: 0, buildings: 0 })
  expect(result.current.skipped).toBe(true)
  expect(backend.analysed()).toHaveLength(0)
})

/** Prostokat kawalka bez licznika budynkow — dokladnie to, co mapa dostaje jako `Bounds`. */
function chunkArea(index: number, plan: AreaPlan = aPlan()): Bounds {
  const chunk = plan.chunks[index]
  return { sw: chunk.sw, ne: chunk.ne }
}

// Sedno tej zmiany po stronie hooka: mapa musi wiedziec, GDZIE model patrzy teraz — sam licznik
// „1 z 2" tego nie mowi. Przed planem nie ma jeszcze zadnego kawalka, wiec nie ma czego rysowac.
it('wystawia kawalek liczony teraz dopiero po planie', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  expect(result.current.analysingChunk).toBeNull()
  expect(result.current.analysedChunks).toEqual([])

  await backend.answer(0, aPlan())

  expect(result.current.analysingChunk).toEqual(chunkArea(0))
  // Nic jeszcze nie wrocilo, wiec policzonych nie ma.
  expect(result.current.analysedChunks).toEqual([])
})

// Mapa nie ma po co znac liczby budynkow w kawalku: to jest postep w panelu, nie geometria.
it('oddaje sam prostokat kawalka, bez licznika budynkow', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())

  expect(result.current.analysingChunk).not.toHaveProperty('buildings')
  expect(Object.keys(result.current.analysingChunk ?? {}).sort()).toEqual(['ne', 'sw'])
})

it('przesuwa aktualny kawalek na nastepny i dopisuje policzony', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  await backend.answer(1, aChunkResult([aRoof({ id: 1 })], 0))

  expect(result.current.analysingChunk).toEqual(chunkArea(1))
  expect(result.current.analysedChunks).toEqual([chunkArea(0)])
})

// Po ostatnim kawalku nie ma „aktualnego", a „policzone" znaczyloby cale zaznaczenie — czyli nic
// nie wnosi. Zostaje sam wynik: pomaranczowe obrysy i prostokat obszaru.
it('czysci oba prostokaty po ostatnim kawalku', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  await backend.answer(1, aChunkResult([aRoof({ id: 1 })], 0))
  await backend.answer(2, aChunkResult([aRoof({ id: 2 })], 0))

  expect(result.current.loading).toBe(false)
  expect(result.current.analysingChunk).toBeNull()
  expect(result.current.analysedChunks).toEqual([])
  // Wynik zostaje — znika sam postep.
  expect(result.current.analysis?.buildings.map((roof) => roof.id)).toEqual([1, 2])
})

// Policzone rosna kawalek po kawalku i wlasnie to robi efekt przemiatania obszaru.
it('policzone kawalki rosna po jednym, w kolejnosci z planu', async () => {
  const backend = queuedFetch()
  /** Trzeci kawalek dalej na wschod, zeby lista policzonych rosla w kolejnosci z planu. */
  const third = { sw: { lng: 21.5865, lat: 51.3555 }, ne: { lng: 21.5925, lat: 51.3629 }, buildings: 88 }
  const plan = aPlan({ chunks: [...aPlan().chunks, third] })
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, plan)
  expect(result.current.analysedChunks).toEqual([])

  await backend.answer(1, aChunkResult([aRoof({ id: 1 })], 0))
  expect(result.current.analysedChunks).toEqual([chunkArea(0, plan)])

  await backend.answer(2, aChunkResult([aRoof({ id: 2 })], 0))
  expect(result.current.analysedChunks).toEqual([chunkArea(0, plan), chunkArea(1, plan)])
  expect(result.current.analysingChunk).toEqual(chunkArea(2, plan))

  await backend.answer(3, aChunkResult([aRoof({ id: 3 })], 0))
  expect(result.current.analysedChunks).toEqual([])
  expect(result.current.analysingChunk).toBeNull()
})

// Jeden kawalek jest rowny calemu zaznaczeniu, wiec jego ramka lezalaby dokladnie na prostokacie
// zeskanowanego obszaru, ktory mapa juz rysuje. Druga ramka na tym samym miejscu to szum.
it('nie wystawia nic do rysowania, gdy plan ma jeden kawalek', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan({ chunks: [aPlan().chunks[0]] }))

  expect(result.current.analysingChunk).toBeNull()
  expect(result.current.analysedChunks).toEqual([])

  await backend.answer(1, aChunkResult([aRoof({ id: 1 })], 0))

  expect(result.current.analysingChunk).toBeNull()
  expect(result.current.analysedChunks).toEqual([])
  // Wynik oczywiscie jest: nie rysujemy postepu, a nie rezygnujemy z analizy.
  expect(result.current.analysis?.buildings.map((roof) => roof.id)).toEqual([1])
})

// Przy bledzie policzone zostaja widoczne: wtedy wlasnie pokazuja, ile obszaru model obejrzal,
// zanim przestal odpowiadac. Gasnie sam kawalek, ktory nie wrocil.
it('po bledzie kawalka zostawia policzone, a aktualny gasi', async () => {
  const backend = queuedFetch()
  const plan = aPlan({ chunks: [...aPlan().chunks, { ...aPlan().chunks[0], buildings: 88 }] })
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, plan)
  await backend.answer(1, aChunkResult([aRoof({ id: 1 })], 0))
  await backend.reject(2, 503, 'The model is not responding.')

  expect(result.current.error).toBe('The model is not responding.')
  expect(result.current.analysedChunks).toEqual([chunkArea(0, plan)])
  expect(result.current.analysingChunk).toBeNull()
})

it('clear i nowe run zdejmuja oba prostokaty', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aPlan())
  await backend.answer(1, aChunkResult([aRoof({ id: 1 })], 0))
  expect(result.current.analysedChunks).toHaveLength(1)

  act(() => result.current.clear())
  expect(result.current.analysingChunk).toBeNull()
  expect(result.current.analysedChunks).toEqual([])

  // Nowe zaznaczenie startuje bez postepu poprzedniego, jeszcze przed odpowiedzia planu.
  act(() => result.current.run(OTHER_BOUNDS))
  expect(result.current.analysingChunk).toBeNull()
  expect(result.current.analysedChunks).toEqual([])
})

// Scalanie jest zwykla funkcja, wiec arytmetyke sprawdzamy bez hooka i bez sieci.
it('mergeAnalyses bez kawalkow nie wymysla wyniku', () => {
  expect(mergeAnalyses([])).toBeNull()
})

it('mergeAnalyses przepuszcza pojedynczy kawalek z liczbami policzonymi z jego ocen', () => {
  const part = aChunkResult([aRoof({ id: 1 }), aRoof({ id: 2, probability: 0.3 })], 5)

  const merged = mergeAnalyses([part])

  expect(merged?.stats).toMatchObject({ analysed: 2, noResult: 5, suspected: 1, suspectedNotListed: 1 })
  expect(merged?.buildings).toEqual(part.buildings)
})

// Przycieta odpowiedz choc jednego kawalka przycina caly wynik: nie mamy wtedy wszystkich ocen,
// wiec panel gasi suwak progu i mowi o tym zdaniem.
it('mergeAnalyses przenosi przyciecie z kawalka na caly wynik', () => {
  const full = aChunkResult([aRoof({ id: 1 })], 0)
  const cut = { ...aChunkResult([aRoof({ id: 2 })], 0), truncated: true }

  expect(mergeAnalyses([full, cut])?.truncated).toBe(true)
  expect(mergeAnalyses([full, full])?.truncated).toBe(false)
})
