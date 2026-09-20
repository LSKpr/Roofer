import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App'
import type { Building, Health } from './api/client'

// Mapa jest zaslepiona: te testy sprawdzaja wiazanie stanu, a nie MapLibre (ktory nie ma w jsdom
// WebGL i ma wlasne testy w src/map/MapView.test.tsx). Zaslepka wystawia sterowanie przez przyciski.
type StubBounds = { ne: { lat: number; lng: number }; sw: { lat: number; lng: number } }

const DRAWN: StubBounds = { ne: { lat: 51.26, lng: 21.1 }, sw: { lat: 51.24, lng: 21.06 } }
/** Zapis prostokata w jednej linii — tyle wystarczy, zeby odroznic obszar od jego braku. */
const DRAWN_LABEL = '21.06,51.24,21.1,51.26'

function areaLabel(area: StubBounds | null | undefined): string {
  if (!area) return 'brak'
  return `${area.sw.lng},${area.sw.lat},${area.ne.lng},${area.ne.lat}`
}

vi.mock('./map/MapView', () => ({
  MapView: ({
    onSelect,
    onZoomChange,
    onDrawComplete,
    basemap,
    drawing,
    scannedArea,
  }: {
    onSelect?: (id: number | null) => void
    onZoomChange?: (zoom: number) => void
    onDrawComplete?: (bounds: StubBounds) => void
    basemap?: string
    drawing?: boolean
    scannedArea?: StubBounds | null
  }) => (
    <div>
      {/* Propsy sterujace mapa wystawiamy jako tekst, zeby dalo sie je sprawdzic bez MapLibre. */}
      <span data-testid="map-basemap">{basemap}</span>
      <span data-testid="map-drawing">{drawing ? 'rysuje' : 'nie rysuje'}</span>
      <span data-testid="map-scanned-area">{areaLabel(scannedArea)}</span>
      <button type="button" onClick={() => onSelect?.(42)}>
        wybierz budynek
      </button>
      <button type="button" onClick={() => onSelect?.(null)}>
        odznacz
      </button>
      <button type="button" onClick={() => onZoomChange?.(9)}>
        oddal
      </button>
      <button type="button" onClick={() => onDrawComplete?.(DRAWN)}>
        narysuj prostokat
      </button>
    </div>
  ),
}))

const HEALTH: Health = { status: 'ok', database: 'ok', postgis: '3.5.2', detail: null }

const BUILDING: Building = {
  id: 42,
  kind: 'building',
  osmType: 'house',
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

// Zaznaczony obszar ma byc widoczny caly czas: dopoki na ekranie jest wynik, na mapie jest
// prostokat, ktorego ten wynik dotyczy.
it('keeps the drawn rectangle on the map once the scan is done', async () => {
  stubApi()

  render(<App />)
  expect(screen.getByTestId('map-scanned-area').textContent).toBe('brak')
  fireEvent.click(screen.getByText('Zaznacz'))
  fireEvent.click(screen.getByText('narysuj prostokat'))

  expect(await screen.findByText('47%')).toBeDefined()
  expect(screen.getByTestId('map-scanned-area').textContent).toBe(DRAWN_LABEL)
})

it('drops the rectangle when the result panel is closed', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Zaznacz'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  await screen.findByText('47%')

  fireEvent.click(screen.getByLabelText('Zamknij'))

  expect(screen.getByTestId('map-scanned-area').textContent).toBe('brak')
})

// Karta budynku zastepuje panel skanu, ale nie uniewaznia wyniku — obszar zostaje na mapie.
it('still shows the rectangle after the user opens a building from the list', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Zaznacz'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  fireEvent.click(await screen.findByText('Działka 142511_2.0012.2.2077/21'))
  await screen.findByText(/141210_5\.0017\.105\/1/)

  expect(screen.getByTestId('map-scanned-area').textContent).toBe(DRAWN_LABEL)
})

// Blad („obszar za duzy") jest wlasnie tym momentem, w ktorym uzytkownik musi zobaczyc,
// co zaznaczyl, zeby poprawic zaznaczenie.
it('keeps the rectangle visible when the scan fails', async () => {
  stubApi({ scan: [400, { detail: 'Zaznaczony obszar jest za duży.' }] })

  render(<App />)
  fireEvent.click(screen.getByText('Zaznacz'))
  fireEvent.click(screen.getByText('narysuj prostokat'))

  expect(await screen.findByText(/za duży/)).toBeDefined()
  expect(screen.getByTestId('map-scanned-area').textContent).toBe(DRAWN_LABEL)
})

// Nowe zaznaczenie nie moze zostac obok starego: stary prostokat znika, zanim powstanie nowy.
it('clears the old rectangle as soon as the user starts drawing again', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Zaznacz'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  await screen.findByText('47%')

  fireEvent.click(screen.getByText('Zaznacz'))

  expect(screen.getByTestId('map-drawing').textContent).toBe('rysuje')
  expect(screen.getByTestId('map-scanned-area').textContent).toBe('brak')
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
