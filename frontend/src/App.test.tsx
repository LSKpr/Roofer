import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App'
import type { Building, Health } from './api/client'

// Mapa jest zaslepiona: te testy sprawdzaja wiazanie stanu, a nie MapLibre (ktory nie ma w jsdom
// WebGL i ma wlasne testy w src/map/MapView.test.tsx). Zaslepka wystawia sterowanie przez przyciski.
vi.mock('./map/MapView', () => ({
  MapView: ({
    onSelect,
    onZoomChange,
  }: {
    onSelect?: (id: number | null) => void
    onZoomChange?: (zoom: number) => void
  }) => (
    <div>
      <button type="button" onClick={() => onSelect?.(42)}>
        wybierz budynek
      </button>
      <button type="button" onClick={() => onSelect?.(null)}>
        odznacz
      </button>
      <button type="button" onClick={() => onZoomChange?.(9)}>
        oddal
      </button>
    </div>
  ),
}))

const HEALTH: Health = { status: 'ok', database: 'ok', postgis: '3.5.2', detail: null }

const BUILDING: Building = {
  id: 42,
  osmId: '382845106',
  kind: 'building',
  name: null,
  areaM2: 106.1,
  centroid: { lng: 21.8287, lat: 52.0721 },
  status: 'listed',
  registryMatches: [
    {
      sourceId: 'budynki_z_azbestem.1310936',
      nrDzialki: '141210_5.0017.105/1',
      recordAreaM2: 106.1,
      overlapM2: 106.1,
      shareBuilding: 1,
      shareRecord: 1,
    },
  ],
  otherIntersecting: 0,
}

function stubApi(overrides: { health?: [number, unknown]; building?: [number, unknown] } = {}) {
  const [healthStatus, healthBody] = overrides.health ?? [200, HEALTH]
  const [buildingStatus, buildingBody] = overrides.building ?? [200, BUILDING]
  const fetchStub = vi.fn((url: string) =>
    Promise.resolve(
      url.includes('/api/buildings/')
        ? { status: buildingStatus, json: async () => buildingBody }
        : { status: healthStatus, json: async () => healthBody },
    ),
  )
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('shows the PostGIS version once the backend answers', async () => {
  stubApi()

  render(<App />)

  expect(await screen.findByText(/PostGIS 3\.5\.2/)).toBeDefined()
})

it('says the database is missing instead of pretending everything is fine', async () => {
  stubApi({
    health: [503, { status: 'degraded', database: 'unavailable', postgis: null, detail: 'connection refused' }],
  })

  render(<App />)

  expect(await screen.findByText(/Backend bez bazy: connection refused/)).toBeDefined()
})

it('reports an unreachable backend', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Failed to fetch')))

  render(<App />)

  expect(await screen.findByText(/Backend niedostepny: Failed to fetch/)).toBeDefined()
})

it('always shows the legend, so the colours are never unexplained', async () => {
  stubApi()

  render(<App />)

  expect(await screen.findByText(/Zgłoszony w rejestrze GeoAzbest/)).toBeDefined()
})

it('opens the building card for the building picked on the map', async () => {
  const fetchStub = stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('wybierz budynek'))

  expect(await screen.findByText(/141210_5\.0017\.105\/1/)).toBeDefined()
  expect(fetchStub).toHaveBeenCalledWith('/api/buildings/42')
})

it('closes the card when the map selection is cleared', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('wybierz budynek'))
  await screen.findByText(/141210_5\.0017\.105\/1/)
  fireEvent.click(screen.getByText('odznacz'))

  expect(screen.queryByText(/141210_5\.0017\.105\/1/)).toBeNull()
})

it('explains an empty map instead of leaving it looking broken', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('oddal'))

  expect(await screen.findByText(/Przybliż, aby zobaczyć obrysy dachów/)).toBeDefined()
})
