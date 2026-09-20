import { afterEach, expect, it, vi } from 'vitest'
import {
  TILES_URL,
  fetchAreaAnalysis,
  fetchAreaLimits,
  fetchBuilding,
  fetchHealth,
  type AreaAnalysis,
  type Bounds,
  type Building,
  type Health,
} from './client'

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

  await expect(fetchHealth('http://api.test')).rejects.toThrow('status 500')
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
  stubFetch(404, { detail: 'There is no building with this identifier.' })

  await expect(fetchBuilding(7, 'http://api.test')).rejects.toThrow('no building with this identifier')
})

const BOUNDS: Bounds = { ne: { lng: 21.61, lat: 51.37 }, sw: { lng: 21.58, lat: 51.35 } }

const ANALYSIS: AreaAnalysis = {
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
}

it('reads the model limits next to the selection limit', async () => {
  const fetchStub = stubFetch(200, { maxAreaKm2: 25, model: { maxBuildings: 100, maxAreaKm2: 4 } })

  await expect(fetchAreaLimits('http://api.test')).resolves.toEqual({
    maxAreaKm2: 25,
    model: { maxBuildings: 100, maxAreaKm2: 4 },
  })
  expect(fetchStub).toHaveBeenCalledWith('http://api.test/api/area/limits')
})

// Backend bez analizy obszaru oddaje sam limit zaznaczenia — front ma z tego wyjsc bez wyjatku.
it('accepts limits without the model section', async () => {
  stubFetch(200, { maxAreaKm2: 25 })

  await expect(fetchAreaLimits('http://api.test')).resolves.toEqual({ maxAreaKm2: 25 })
})

it('asks the model about the same rectangle the scan used', async () => {
  const fetchStub = stubFetch(200, ANALYSIS)

  await expect(fetchAreaAnalysis(BOUNDS, 'http://api.test')).resolves.toEqual(ANALYSIS)
  expect(fetchStub).toHaveBeenCalledWith('http://api.test/api/area/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(BOUNDS),
  })
})

// Tekst z `detail` tlumaczy, ile budynkow zaznaczono wobec limitu — przerobiony na wlasny
// komunikat stracilby te liczbe.
it('passes the backend detail through untouched', async () => {
  stubFetch(400, { detail: 'The model accepts up to 100 buildings; this area has 1,338.' })

  await expect(fetchAreaAnalysis(BOUNDS, 'http://api.test')).rejects.toThrow(
    'The model accepts up to 100 buildings; this area has 1,338.',
  )
})

it('says something instead of nothing when the model is unreachable', async () => {
  stubFetch(503, {})

  await expect(fetchAreaAnalysis(BOUNDS, 'http://api.test')).rejects.toThrow('Could not analyse the area.')
})

it('rejects an unexpected status from the analysis endpoint', async () => {
  stubFetch(500, {})

  await expect(fetchAreaAnalysis(BOUNDS, 'http://api.test')).rejects.toThrow('status 500')
})
