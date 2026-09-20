import { afterEach, expect, it, vi } from 'vitest'
import { TILES_URL, fetchBuilding, fetchHealth, type Building, type Health } from './client'

const HEALTHY: Health = { status: 'ok', database: 'ok', postgis: '3.5.1', detail: null }

function stubFetch(status: number, body: unknown) {
  const fetchStub = vi.fn().mockResolvedValue({ status, json: async () => body })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('asks the configured backend for its health', async () => {
  const fetchStub = stubFetch(200, HEALTHY)

  await expect(fetchHealth('http://api.test')).resolves.toEqual(HEALTHY)
  expect(fetchStub).toHaveBeenCalledWith('http://api.test/api/health')
})

it('asks its own origin when no base url is configured', async () => {
  const fetchStub = stubFetch(200, HEALTHY)

  await fetchHealth('')

  expect(fetchStub).toHaveBeenCalledWith('/api/health')
})

it('treats 503 as data, because a degraded backend still answers', async () => {
  const degraded: Health = { status: 'degraded', database: 'unavailable', postgis: null, detail: 'connection refused' }
  stubFetch(503, degraded)

  await expect(fetchHealth('http://api.test')).resolves.toEqual(degraded)
})

it('rejects on any other status code', async () => {
  stubFetch(500, {})

  await expect(fetchHealth('http://api.test')).rejects.toThrow('kodem 500')
})

it('keeps the z/x/y placeholders that MapLibre fills in itself', () => {
  expect(TILES_URL).toContain('/api/tiles/buildings/{z}/{x}/{y}.mvt')
})

it('reads a single building', async () => {
  const building: Building = {
    id: 7,
    kind: 'building',
    osmType: 'house',
    name: null,
    areaM2: 106.1,
    centroid: { lng: 21.8287, lat: 52.0721 },
    status: 'listed',
    registryMatches: [],
    otherIntersecting: 0,
  }
  const fetchStub = stubFetch(200, building)

  await expect(fetchBuilding(7, 'http://api.test')).resolves.toEqual(building)
  expect(fetchStub).toHaveBeenCalledWith('http://api.test/api/buildings/7')
})

it('explains a missing building instead of showing a bare 404', async () => {
  stubFetch(404, { detail: 'Nie ma budynku o tym identyfikatorze.' })

  await expect(fetchBuilding(7, 'http://api.test')).rejects.toThrow('Nie ma budynku')
})
