import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAreaScan } from './useAreaScan'
import type { AreaScan, Bounds } from '../api/client'

const BOUNDS: Bounds = { ne: { lng: 21.61, lat: 51.37 }, sw: { lng: 21.58, lat: 51.35 } }
const OTHER_BOUNDS: Bounds = { ne: { lng: 20.99, lat: 52.24 }, sw: { lng: 20.96, lat: 52.22 } }

function aScan(overrides: Partial<AreaScan> = {}): AreaScan {
  return {
    stats: {
      total: 1338,
      listed: 624,
      notListed: 714,
      listedShare: 0.4664,
      roofAreaM2: 158292.7,
      listedRoofAreaM2: 60558.1,
      registryRecords: 681,
    },
    listedBuildings: [{ id: 101, areaM2: 148.6, centroid: { lng: 21.59, lat: 51.36 }, nrDzialki: '1417/2' }],
    truncated: false,
    areaKm2: 4.012,
    ...overrides,
  }
}

type Response = { status: number; json: () => Promise<unknown> }

/**
 * Odpowiedzi rozwiazywane recznie: kazde wywolanie fetch odklada swoj `resolve` do kolejki,
 * wiec test decyduje, ktory skan wraca pierwszy. Inaczej nie da sie odtworzyc wyscigu.
 */
function queuedFetch() {
  const queue: ((response: Response) => void)[] = []
  const stub = vi.fn(() => new Promise<Response>((resolve) => queue.push(resolve)))
  vi.stubGlobal('fetch', stub)
  return {
    pending: () => queue.length,
    async answer(index: number, scan: AreaScan) {
      await act(async () => queue[index]({ status: 200, json: async () => scan }))
    },
    async reject(index: number, status: number, detail: string) {
      await act(async () => queue[index]({ status, json: async () => ({ detail }) }))
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('nie pyta o nic, dopoki nikt nie zlecil skanu', () => {
  const fetchStub = vi.fn()
  vi.stubGlobal('fetch', fetchStub)

  const { result } = renderHook(() => useAreaScan())

  expect(result.current).toMatchObject({ scan: null, loading: false, error: null })
  expect(fetchStub).not.toHaveBeenCalled()
})

it('wlacza loading od wywolania run i gasi je razem z wynikiem', async () => {
  const backend = queuedFetch()
  const scan = aScan()
  const { result } = renderHook(() => useAreaScan())

  act(() => result.current.run(BOUNDS))

  expect(result.current.loading).toBe(true)
  expect(result.current.scan).toBeNull()

  await backend.answer(0, scan)

  expect(result.current.scan).toEqual(scan)
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()
})

it('zamienia blad z backendu na komunikat, nie na wyjatek', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaScan())

  act(() => result.current.run(BOUNDS))
  await backend.reject(0, 400, 'The area is 41 km2, and the maximum is 25 km2 — select a smaller fragment.')

  expect(result.current.error).toBe('The area is 41 km2, and the maximum is 25 km2 — select a smaller fragment.')
  expect(result.current.scan).toBeNull()
  expect(result.current.loading).toBe(false)
})

it('nie pozwala porzuconemu skanowi nadpisac nowszego, nawet gdy wroci pozniej', async () => {
  const backend = queuedFetch()
  const first = aScan({ areaKm2: 1.5, stats: { ...aScan().stats, total: 11 } })
  const second = aScan({ areaKm2: 4.012 })
  const { result } = renderHook(() => useAreaScan())

  act(() => result.current.run(BOUNDS))
  act(() => result.current.run(OTHER_BOUNDS))
  expect(backend.pending()).toBe(2)

  await backend.answer(1, second)
  expect(result.current.scan).toEqual(second)

  // Spozniona odpowiedz pierwszego zaznaczenia: nie jest wynikiem i nie cofa panelu w loading.
  await backend.answer(0, first)

  expect(result.current.scan).toEqual(second)
  expect(result.current.loading).toBe(false)
})

it('clear czysci wynik i blad', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaScan())

  act(() => result.current.run(BOUNDS))
  await backend.answer(0, aScan())

  act(() => result.current.clear())

  expect(result.current.scan).toBeNull()
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()

  act(() => result.current.run(BOUNDS))
  await backend.reject(1, 503, 'The database is not responding.')
  expect(result.current.error).toBe('The database is not responding.')

  act(() => result.current.clear())
  expect(result.current.error).toBeNull()
})

it('clear porzuca skan w locie, a jego odpowiedz nic nie wraca', async () => {
  const backend = queuedFetch()
  const { result } = renderHook(() => useAreaScan())

  act(() => result.current.run(BOUNDS))
  act(() => result.current.clear())

  expect(result.current.loading).toBe(false)

  await backend.answer(0, aScan())

  expect(result.current.scan).toBeNull()
  expect(result.current.loading).toBe(false)
})
