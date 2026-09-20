import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { usePlaceSearch, SEARCH_DEBOUNCE_MS } from './usePlaceSearch'
import type { Place } from '../api/client'

const ZWOLEN: Place = {
  label: 'Zwoleń, gmina Zwoleń, powiat zwoleński, województwo mazowieckie, 26-700, Polska',
  lat: 51.3557,
  lng: 21.5919,
  bbox: [51.33, 21.56, 51.38, 21.62],
  kind: 'town',
}

/** Kształt odpowiedzi jest sprawdzany w client.test.ts; tu wystarczy tyle, ile czyta fetchPlaces. */
function okResponse(results: Place[]): Response {
  return { status: 200, json: async () => ({ results }) } as unknown as Response
}

function errorResponse(status: number): Response {
  return { status, json: async () => ({}) } as unknown as Response
}

function stubFetch(response: Response) {
  const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

/** Debounce jest zegarem, wiec zegar musi byc sterowany, a nie odczekiwany. */
async function tick(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('does not ask the network about a phrase shorter than three characters', async () => {
  const fetchStub = stubFetch(okResponse([ZWOLEN]))

  const { result } = renderHook(() => usePlaceSearch())
  act(() => result.current.setQuery('zw'))
  await tick(2000)

  expect(fetchStub).not.toHaveBeenCalled()
  expect(result.current.results).toEqual([])
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()
})

it('drops results when the phrase gets too short again', async () => {
  stubFetch(okResponse([ZWOLEN]))

  const { result } = renderHook(() => usePlaceSearch())
  act(() => result.current.setQuery('zwole'))
  await tick(SEARCH_DEBOUNCE_MS)
  expect(result.current.results).toEqual([ZWOLEN])

  act(() => result.current.setQuery('zw'))

  expect(result.current.results).toEqual([])
  expect(result.current.loading).toBe(false)
})

it('sends one request for three quick edits of the phrase', async () => {
  const fetchStub = stubFetch(okResponse([ZWOLEN]))

  const { result } = renderHook(() => usePlaceSearch())
  act(() => result.current.setQuery('zwo'))
  await tick(100)
  act(() => result.current.setQuery('zwol'))
  await tick(100)
  act(() => result.current.setQuery('zwole'))
  expect(fetchStub).not.toHaveBeenCalled()

  await tick(SEARCH_DEBOUNCE_MS)

  expect(fetchStub).toHaveBeenCalledTimes(1)
  expect(String(fetchStub.mock.calls[0][0])).toContain('q=zwole')
})

it('reports loading until the answer to the current phrase arrives', async () => {
  stubFetch(okResponse([ZWOLEN]))

  const { result } = renderHook(() => usePlaceSearch())
  act(() => result.current.setQuery('zwole'))
  expect(result.current.loading).toBe(true)

  await tick(SEARCH_DEBOUNCE_MS)

  expect(result.current.loading).toBe(false)
  expect(result.current.results).toEqual([ZWOLEN])
  expect(result.current.error).toBeNull()
})

it('keeps the rate limit message the client produced for 429', async () => {
  stubFetch(errorResponse(429))

  const { result } = renderHook(() => usePlaceSearch())
  act(() => result.current.setQuery('zwole'))
  await tick(SEARCH_DEBOUNCE_MS)

  expect(result.current.error).toMatch(/Za dużo zapytań/)
  expect(result.current.results).toEqual([])
  expect(result.current.loading).toBe(false)
})

it('keeps the outage message the client produced for 503', async () => {
  stubFetch(errorResponse(503))

  const { result } = renderHook(() => usePlaceSearch())
  act(() => result.current.setQuery('zwole'))
  await tick(SEARCH_DEBOUNCE_MS)

  expect(result.current.error).toBe('Wyszukiwarka miejsc nie odpowiada.')
})

it('clears the phrase and the results', async () => {
  stubFetch(okResponse([ZWOLEN]))

  const { result } = renderHook(() => usePlaceSearch())
  act(() => result.current.setQuery('zwole'))
  await tick(SEARCH_DEBOUNCE_MS)
  expect(result.current.results).toEqual([ZWOLEN])

  act(() => result.current.clear())

  expect(result.current.query).toBe('')
  expect(result.current.results).toEqual([])
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()
})
