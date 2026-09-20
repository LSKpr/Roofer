import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAreaAnalysis } from './useAreaAnalysis'
import type { AreaAnalysis, Bounds } from '../api/client'

const BOUNDS: Bounds = { ne: { lng: 21.61, lat: 51.37 }, sw: { lng: 21.58, lat: 51.35 } }
const OTHER_BOUNDS: Bounds = { ne: { lng: 20.99, lat: 52.24 }, sw: { lng: 20.96, lat: 52.22 } }

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
    buildings: [
      {
        id: 27469148,
        probability: 0.72,
        listed: false,
        areaM2: 163,
        geometry: { type: 'Polygon', coordinates: [[[21.59, 51.36], [21.591, 51.36], [21.591, 51.361], [21.59, 51.36]]] },
      },
    ],
    truncated: false,
    ...overrides,
  }
}

type Response = { status: number; json: () => Promise<unknown> }

/**
 * Odpowiedzi rozwiazywane recznie: kazde wywolanie fetch odklada swoj `resolve` do kolejki,
 * wiec test decyduje, ktora ocena wraca pierwsza. Inaczej nie da sie odtworzyc wyscigu.
 */
function queuedFetch() {
  const queue: ((response: Response) => void)[] = []
  const stub = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>((resolve) => queue.push(resolve)))
  vi.stubGlobal('fetch', stub)
  return {
    calls: stub,
    pending: () => queue.length,
    async answer(index: number, analysis: AreaAnalysis) {
      await act(async () => queue[index]({ status: 200, json: async () => analysis }))
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
it('nie pyta modelu o nic, dopoki nikt nie zlecil analizy', () => {
  const fetchStub = vi.fn()
  vi.stubGlobal('fetch', fetchStub)

  const { result } = renderHook(() => useAreaAnalysis())

  expect(result.current).toMatchObject({ analysis: null, loading: false, error: null })
  expect(fetchStub).not.toHaveBeenCalled()
})

it('wysyla prostokat na /api/area/analyze i gasi loading razem z wynikiem', async () => {
  const backend = queuedFetch()
  const analysis = anAnalysis()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))

  expect(result.current.loading).toBe(true)
  expect(result.current.analysis).toBeNull()
  expect(backend.calls.mock.calls[0][0]).toBe('/api/area/analyze')

  await backend.answer(0, analysis)

  expect(result.current.analysis).toEqual(analysis)
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()
})

it('zamienia blad z backendu na komunikat, nie na wyjatek', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.reject(0, 400, 'The model accepts up to 100 buildings; this area has 1,338.')

  expect(result.current.error).toBe('The model accepts up to 100 buildings; this area has 1,338.')
  expect(result.current.analysis).toBeNull()
  expect(result.current.loading).toBe(false)
})

it('nie pozwala porzuconej analizie nadpisac nowszej, nawet gdy wroci pozniej', async () => {
  const backend = queuedFetch()
  const first = anAnalysis({ stats: { ...anAnalysis().stats, suspectedNotListed: 1 } })
  const second = anAnalysis({ stats: { ...anAnalysis().stats, suspectedNotListed: 14 } })
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  act(() => result.current.run(OTHER_BOUNDS))
  expect(backend.pending()).toBe(2)

  await backend.answer(1, second)
  expect(result.current.analysis).toEqual(second)

  // Spozniona odpowiedz pierwszego obszaru: nie jest wynikiem i nie cofa panelu w loading.
  await backend.answer(0, first)

  expect(result.current.analysis).toEqual(second)
  expect(result.current.loading).toBe(false)
})

it('clear czysci wynik i blad', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, anAnalysis())

  act(() => result.current.clear())

  expect(result.current.analysis).toBeNull()
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()

  act(() => result.current.run(BOUNDS))
  await backend.reject(1, 503, 'The model is not responding.')
  expect(result.current.error).toBe('The model is not responding.')

  act(() => result.current.clear())
  expect(result.current.error).toBeNull()
})

it('clear porzuca analize w locie, a jej odpowiedz nic nie wraca', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaAnalysis())

  act(() => result.current.run(BOUNDS))
  act(() => result.current.clear())

  expect(result.current.loading).toBe(false)

  await backend.answer(0, anAnalysis())

  expect(result.current.analysis).toBeNull()
  expect(result.current.loading).toBe(false)
})
