import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useRoofAnalysis } from './useRoofAnalysis'
import type { RoofAnalysis } from '../api/client'

function anAnalysis(overrides: Partial<RoofAnalysis> = {}): RoofAnalysis {
  return {
    source: 'model',
    verdict: 'suspected',
    probability: 0.72,
    modelName: 'eternit-v1',
    note: 'Ocena z jednego zdjęcia lotniczego. Nie zastępuje oględzin ani badania próbki.',
    ...overrides,
  }
}

type Response = { status: number; json: () => Promise<unknown> }

type Pending = { url: string; settle: (response: Response) => void }

/**
 * Odpowiedzi rozwiazywane recznie: kazde wywolanie fetch odklada swoj `resolve` do kolejki,
 * wiec test decyduje, ktory budynek wraca pierwszy. Inaczej nie da sie odtworzyc wyscigu.
 */
function queuedFetch() {
  const queue: Pending[] = []
  const stub = vi.fn((url: string) => new Promise<Response>((resolve) => queue.push({ url, settle: resolve })))
  vi.stubGlobal('fetch', stub)
  return {
    urls: () => queue.map((request) => request.url),
    pending: () => queue.length,
    async answer(index: number, analysis: RoofAnalysis) {
      await act(async () => queue[index].settle({ status: 200, json: async () => analysis }))
    },
    async fail(index: number, status: number) {
      await act(async () => queue[index].settle({ status, json: async () => ({}) }))
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('nie pyta o nic, dopoki nie wybrano budynku', () => {
  const fetchStub = vi.fn()
  vi.stubGlobal('fetch', fetchStub)

  const { result } = renderHook(() => useRoofAnalysis(null))

  expect(result.current).toEqual({ analysis: null, loading: false, error: null })
  expect(fetchStub).not.toHaveBeenCalled()
})

it('zglasza wczytywanie, a potem ocene pokrycia', async () => {
  const backend = queuedFetch()
  const analysis = anAnalysis()

  const { result } = renderHook(() => useRoofAnalysis(42))

  expect(result.current).toEqual({ analysis: null, loading: true, error: null })

  await backend.answer(0, analysis)

  expect(result.current.analysis).toEqual(analysis)
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()
})

it('zamienia blad z backendu na komunikat, nie na wyjatek', async () => {
  const backend = queuedFetch()

  const { result } = renderHook(() => useRoofAnalysis(42))
  await backend.fail(0, 404)

  expect(result.current.error).toMatch(/Nie ma budynku/)
  expect(result.current.analysis).toBeNull()
  expect(result.current.loading).toBe(false)
})

it('pyta o analize kazdego wybranego budynku osobno', async () => {
  const backend = queuedFetch()

  const { rerender } = renderHook(({ id }: { id: number | null }) => useRoofAnalysis(id), {
    initialProps: { id: 42 as number | null },
  })
  await backend.answer(0, anAnalysis())

  rerender({ id: 43 })

  expect(backend.urls()).toHaveLength(2)
  expect(backend.urls()[0]).toContain('/api/buildings/42/analysis')
  expect(backend.urls()[1]).toContain('/api/buildings/43/analysis')
})

it('zmiana budynku nie pokazuje oceny poprzedniego, tylko wczytywanie', async () => {
  const backend = queuedFetch()
  const first = anAnalysis({ verdict: 'suspected', probability: 0.72 })

  const { result, rerender } = renderHook(({ id }: { id: number | null }) => useRoofAnalysis(id), {
    initialProps: { id: 42 as number | null },
  })
  await backend.answer(0, first)
  expect(result.current.analysis).toEqual(first)

  rerender({ id: 43 })

  expect(result.current).toEqual({ analysis: null, loading: true, error: null })
})

it('nie pozwala porzuconej odpowiedzi nadpisac nowszej, nawet gdy wroci pozniej', async () => {
  const backend = queuedFetch()
  const first = anAnalysis({ verdict: 'suspected', probability: 0.91 })
  const second = anAnalysis({ verdict: 'unlikely', probability: 0.08 })

  const { result, rerender } = renderHook(({ id }: { id: number | null }) => useRoofAnalysis(id), {
    initialProps: { id: 42 as number | null },
  })
  rerender({ id: 43 })
  expect(backend.pending()).toBe(2)

  await backend.answer(1, second)
  expect(result.current.analysis).toEqual(second)

  // Spozniona odpowiedz porzuconego budynku: nie jest wynikiem i nie cofa sekcji w loading.
  await backend.answer(0, first)

  expect(result.current.analysis).toEqual(second)
  expect(result.current.loading).toBe(false)
})

it('porzucenie wyboru czysci ocene poprzedniego budynku', async () => {
  const backend = queuedFetch()

  const { result, rerender } = renderHook(({ id }: { id: number | null }) => useRoofAnalysis(id), {
    initialProps: { id: 42 as number | null },
  })
  await backend.answer(0, anAnalysis())

  rerender({ id: null })

  expect(result.current).toEqual({ analysis: null, loading: false, error: null })
})

it('bledna odpowiedz porzuconego budynku nie trafia do nowszego', async () => {
  const backend = queuedFetch()
  const second = anAnalysis({ verdict: 'unknown', probability: null })

  const { result, rerender } = renderHook(({ id }: { id: number | null }) => useRoofAnalysis(id), {
    initialProps: { id: 42 as number | null },
  })
  rerender({ id: 43 })

  await backend.answer(1, second)
  await backend.fail(0, 500)

  expect(result.current.analysis).toEqual(second)
  expect(result.current.error).toBeNull()
})
