import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App'
import type { Building, Health } from './api/client'

// Mapa jest zaslepiona: te testy sprawdzaja wiazanie stanu, a nie MapLibre (ktory nie ma w jsdom
// WebGL i ma wlasne testy w src/map/MapView.test.tsx). Zaslepka wystawia sterowanie przez przyciski.
vi.mock('./map/MapView', () => ({
  MapView: ({
    onSelect,
    onZoomChange,
    onDrawComplete,
    basemap,
    drawing,
  }: {
    onSelect?: (id: number | null) => void
    onZoomChange?: (zoom: number) => void
    onDrawComplete?: (bounds: { ne: { lat: number; lng: number }; sw: { lat: number; lng: number } }) => void
    basemap?: string
    drawing?: boolean
  }) => (
    <div>
      {/* Propsy sterujace mapa wystawiamy jako tekst, zeby dalo sie je sprawdzic bez MapLibre. */}
      <span data-testid="map-basemap">{basemap}</span>
      <span data-testid="map-drawing">{drawing ? 'rysuje' : 'nie rysuje'}</span>
      <button type="button" onClick={() => onSelect?.(42)}>
        wybierz budynek
      </button>
      <button type="button" onClick={() => onSelect?.(null)}>
        odznacz
      </button>
      <button type="button" onClick={() => onZoomChange?.(9)}>
        oddal
      </button>
      <button
        type="button"
        onClick={() => onDrawComplete?.({ ne: { lat: 51.26, lng: 21.1 }, sw: { lat: 51.24, lng: 21.06 } })}
      >
        narysuj prostokat
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

const SCAN = {
  stats: {
    total: 1338,
    listed: 624,
    notListed: 714,
    listedShare: 0.4664,
    roofAreaM2: 158292.7,
    listedRoofAreaM2: 60558.1,
    registryRecords: 681,
  },
  listedBuildings: [{ id: 42, areaM2: 479.5, centroid: { lng: 21.07, lat: 51.246 }, nrDzialki: '142511_2.0012.2.2077/21' }],
  truncated: false,
  areaKm2: 4.0,
}

function stubApi(overrides: { health?: [number, unknown]; building?: [number, unknown]; scan?: [number, unknown] } = {}) {
  const [healthStatus, healthBody] = overrides.health ?? [200, HEALTH]
  const [buildingStatus, buildingBody] = overrides.building ?? [200, BUILDING]
  const [scanStatus, scanBody] = overrides.scan ?? [200, SCAN]
  const fetchStub = vi.fn((url: string) => {
    if (url.includes('/api/area/limits')) return Promise.resolve({ status: 200, json: async () => ({ maxAreaKm2: 25 }) })
    if (url.includes('/api/area/scan')) return Promise.resolve({ status: scanStatus, json: async () => scanBody })
    if (url.includes('/api/buildings/')) return Promise.resolve({ status: buildingStatus, json: async () => buildingBody })
    return Promise.resolve({ status: healthStatus, json: async () => healthBody })
  })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// Stan backendu jest teraz kropka z podpowiedzia, nie belka nad mapa: sprawdzamy `title`,
// bo to ten sam tekst, ktory dostaje czytnik ekranu.
it('shows the PostGIS version once the backend answers', async () => {
  stubApi()

  render(<App />)

  const dot = await screen.findByTestId('backend-status')
  await waitFor(() => expect(dot.getAttribute('title')).toMatch(/PostGIS 3\.5\.2/))
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

it('lets the user search for a place', async () => {
  stubApi()

  render(<App />)

  expect(await screen.findByLabelText('Szukaj miejscowości lub adresu')).toBeDefined()
})

it('hands the chosen basemap to the map', async () => {
  stubApi()

  render(<App />)
  expect(screen.getByTestId('map-basemap').textContent).toBe('standard')

  fireEvent.click(screen.getByText('Ortofoto'))

  expect(screen.getByTestId('map-basemap').textContent).toBe('orthophoto')
})

it('shows the area limit the backend reports, instead of a hardcoded number', async () => {
  stubApi()

  render(<App />)

  expect(await screen.findByText(/maks\. 25 km²/)).toBeDefined()
})

it('scans the rectangle the user drew and shows the share of listed buildings', async () => {
  const fetchStub = stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Zaznacz'))
  expect(screen.getByTestId('map-drawing').textContent).toBe('rysuje')

  fireEvent.click(screen.getByText('narysuj prostokat'))

  expect(await screen.findByText('47%')).toBeDefined()
  expect(screen.getByTestId('map-drawing').textContent).toBe('nie rysuje')
  const scanCall = fetchStub.mock.calls.find((call) => String(call[0]).includes('/api/area/scan'))
  expect(scanCall).toBeDefined()
})

it('opens the building card for a row picked in the scan result', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Zaznacz'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  fireEvent.click(await screen.findByText('Działka 142511_2.0012.2.2077/21'))

  expect(await screen.findByText(/141210_5\.0017\.105\/1/)).toBeDefined()
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
