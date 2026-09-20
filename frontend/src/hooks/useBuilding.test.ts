import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useBuilding } from './useBuilding'
import type { Building } from '../api/client'

const BUILDING: Building = {
  id: 42,
  osmId: '1',
  kind: 'building',
  name: null,
  areaM2: 100,
  centroid: { lng: 21, lat: 52 },
  status: 'not_listed',
  registryMatches: [],
  otherIntersecting: 0,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('does not ask for anything when nothing is selected', () => {
  const fetchStub = vi.fn()
  vi.stubGlobal('fetch', fetchStub)

  const { result } = renderHook(() => useBuilding(null))

  expect(result.current).toEqual({ building: null, loading: false, error: null })
  expect(fetchStub).not.toHaveBeenCalled()
})

it('reports loading and then the building', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, json: async () => BUILDING }))

  const { result } = renderHook(() => useBuilding(42))

  expect(result.current.loading).toBe(true)
  await waitFor(() => expect(result.current.building).toEqual(BUILDING))
  expect(result.current.loading).toBe(false)
})

it('keeps the error message the backend gave', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 404, json: async () => ({}) }))

  const { result } = renderHook(() => useBuilding(42))

  await waitFor(() => expect(result.current.error).toMatch(/Nie ma budynku/))
  expect(result.current.building).toBeNull()
})

it('clears the previous building when the selection is dropped', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, json: async () => BUILDING }))

  const { result, rerender } = renderHook(({ id }: { id: number | null }) => useBuilding(id), {
    initialProps: { id: 42 as number | null },
  })
  await waitFor(() => expect(result.current.building).toEqual(BUILDING))

  rerender({ id: null })

  expect(result.current).toEqual({ building: null, loading: false, error: null })
})
