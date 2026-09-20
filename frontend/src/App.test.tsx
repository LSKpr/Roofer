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

type StubRoof = { id: number; probability: number }

/** Mapa dostaje liste dachow; w tescie wystarcza ich identyfikatory w jednej linii. */
function roofsLabel(roofs: StubRoof[] | null | undefined): string {
  if (!roofs) return 'brak'
  return roofs.map((roof) => roof.id).join(',')
}

vi.mock('./map/MapView', () => ({
  MapView: ({
    onSelect,
    onZoomChange,
    onDrawComplete,
    basemap,
    drawing,
    scannedArea,
    showRegistry,
    suspectedRoofs,
  }: {
    onSelect?: (id: number | null) => void
    onZoomChange?: (zoom: number) => void
    onDrawComplete?: (bounds: StubBounds) => void
    basemap?: string
    drawing?: boolean
    scannedArea?: StubBounds | null
    showRegistry?: boolean
    suspectedRoofs?: StubRoof[] | null
  }) => (
    <div>
      {/* Propsy sterujace mapa wystawiamy jako tekst, zeby dalo sie je sprawdzic bez MapLibre. */}
      <span data-testid="map-basemap">{basemap}</span>
      <span data-testid="map-drawing">{drawing ? 'rysuje' : 'nie rysuje'}</span>
      <span data-testid="map-scanned-area">{areaLabel(scannedArea)}</span>
      <span data-testid="map-suspected-roofs">{roofsLabel(suspectedRoofs)}</span>
      {/* Tekst, a nie booleana: `undefined` ma byc widoczny jako blad, a nie jako „wylaczone". */}
      <span data-testid="map-show-registry">{String(showRegistry)}</span>
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

// Obszar miesci sie w limitach modelu (100 budynkow, 4 km2), wiec przycisk analizy jest czynny.
const SCAN = {
  stats: {
    total: 74,
    listed: 35,
    notListed: 39,
    listedShare: 0.4664,
    roofAreaM2: 9123.4,
    listedRoofAreaM2: 4021.1,
    registryRecords: 38,
  },
  listedBuildings: [{ id: 42, areaM2: 479.5, centroid: { lng: 21.07, lat: 51.246 }, nrDzialki: '142511_2.0012.2.2077/21' }],
  truncated: false,
  areaKm2: 0.6,
}

/**
 * Trzeci dach ma ocene ponizej progu — mapa nie ma prawa go dostac.
 *
 * Statystyki sa zgodne z tymi trzema ocenami, bo panel przelicza je u siebie: przy progu 0,5
 * z flaga sa 42 i 77, z czego niezgloszony jest tylko 42.
 */
const ANALYSIS = {
  stats: {
    analysed: 3,
    noResult: 1,
    suspected: 2,
    suspectedShare: 0.6667,
    suspectedNotListed: 1,
    suspectedListed: 1,
    listedNotSuspected: 0,
    suspectedRoofAreaM2: 373,
    threshold: 0.5,
    modelName: '70b702',
  },
  buildings: [
    { id: 42, probability: 0.72, listed: false, areaM2: 163, geometry: { type: 'Polygon', coordinates: [] } },
    { id: 77, probability: 0.81, listed: true, areaM2: 210, geometry: { type: 'Polygon', coordinates: [] } },
    { id: 99, probability: 0.31, listed: false, areaM2: 88, geometry: { type: 'Polygon', coordinates: [] } },
  ],
  truncated: false,
}

const LIMITS = { maxAreaKm2: 25, model: { maxBuildings: 100, maxAreaKm2: 4 } }

function stubApi(
  overrides: {
    health?: [number, unknown]
    building?: [number, unknown]
    scan?: [number, unknown]
    analysis?: [number, unknown]
  } = {},
) {
  const [healthStatus, healthBody] = overrides.health ?? [200, HEALTH]
  const [buildingStatus, buildingBody] = overrides.building ?? [200, BUILDING]
  const [scanStatus, scanBody] = overrides.scan ?? [200, SCAN]
  const [analysisStatus, analysisBody] = overrides.analysis ?? [200, ANALYSIS]
  const fetchStub = vi.fn((url: string) => {
    if (url.includes('/api/area/limits')) return Promise.resolve({ status: 200, json: async () => LIMITS })
    if (url.includes('/api/area/scan')) return Promise.resolve({ status: scanStatus, json: async () => scanBody })
    if (url.includes('/api/area/analyze')) return Promise.resolve({ status: analysisStatus, json: async () => analysisBody })
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

  expect(await screen.findByText(/Backend without a database: connection refused/)).toBeDefined()
})

it('reports an unreachable backend', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Failed to fetch')))

  render(<App />)

  expect(await screen.findByText(/Backend unavailable: Failed to fetch/)).toBeDefined()
})

it('lets the user search for a place', async () => {
  stubApi()

  render(<App />)

  expect(await screen.findByLabelText('Search for a place or address')).toBeDefined()
})

it('hands the chosen basemap to the map', async () => {
  stubApi()

  render(<App />)
  expect(screen.getByTestId('map-basemap').textContent).toBe('standard')

  fireEvent.click(screen.getByText('Aerial'))

  expect(screen.getByTestId('map-basemap').textContent).toBe('orthophoto')
})

it('shows the area limit the backend reports, instead of a hardcoded number', async () => {
  stubApi()

  render(<App />)

  expect(await screen.findByText(/max 25 km²/)).toBeDefined()
})

it('scans the rectangle the user drew and shows the share of listed buildings', async () => {
  const fetchStub = stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Select'))
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
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  fireEvent.click(await screen.findByText('Parcel 142511_2.0012.2.2077/21'))

  expect(await screen.findByText(/141210_5\.0017\.105\/1/)).toBeDefined()
})

// Zaznaczony obszar ma byc widoczny caly czas: dopoki na ekranie jest wynik, na mapie jest
// prostokat, ktorego ten wynik dotyczy.
it('keeps the drawn rectangle on the map once the scan is done', async () => {
  stubApi()

  render(<App />)
  expect(screen.getByTestId('map-scanned-area').textContent).toBe('brak')
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))

  expect(await screen.findByText('47%')).toBeDefined()
  expect(screen.getByTestId('map-scanned-area').textContent).toBe(DRAWN_LABEL)
})

it('drops the rectangle when the result panel is closed', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  await screen.findByText('47%')

  fireEvent.click(screen.getByLabelText('Close'))

  expect(screen.getByTestId('map-scanned-area').textContent).toBe('brak')
})

// Karta budynku zastepuje panel skanu, ale nie uniewaznia wyniku — obszar zostaje na mapie.
it('still shows the rectangle after the user opens a building from the list', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  fireEvent.click(await screen.findByText('Parcel 142511_2.0012.2.2077/21'))
  await screen.findByText(/141210_5\.0017\.105\/1/)

  expect(screen.getByTestId('map-scanned-area').textContent).toBe(DRAWN_LABEL)
})

// Blad („obszar za duzy") jest wlasnie tym momentem, w ktorym uzytkownik musi zobaczyc,
// co zaznaczyl, zeby poprawic zaznaczenie.
it('keeps the rectangle visible when the scan fails', async () => {
  stubApi({ scan: [400, { detail: 'The selected area is too large.' }] })

  render(<App />)
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))

  expect(await screen.findByText(/too large/)).toBeDefined()
  expect(screen.getByTestId('map-scanned-area').textContent).toBe(DRAWN_LABEL)
})

// Nowe zaznaczenie nie moze zostac obok starego: stary prostokat znika, zanim powstanie nowy.
it('clears the old rectangle as soon as the user starts drawing again', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  await screen.findByText('47%')

  fireEvent.click(screen.getByText('Select'))

  expect(screen.getByTestId('map-drawing').textContent).toBe('rysuje')
  expect(screen.getByTestId('map-scanned-area').textContent).toBe('brak')
})

it('always shows the legend, so the colours are never unexplained', async () => {
  stubApi()

  render(<App />)

  expect(await screen.findByText(/Listed in the GeoAzbest register/)).toBeDefined()
})

// Przelacznik rejestru startuje wlaczony: mapa ma wygladac tak samo jak przed jego dodaniem.
it('starts with the registry highlight on', async () => {
  stubApi()

  render(<App />)

  expect(screen.getByTestId('map-show-registry').textContent).toBe('true')
  expect((screen.getByLabelText('Highlight buildings listed in the register') as HTMLInputElement).checked).toBe(true)
})

it('turns the registry highlight off for the map when the checkbox is unticked', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByLabelText('Highlight buildings listed in the register'))

  expect(screen.getByTestId('map-show-registry').textContent).toBe('false')

  fireEvent.click(screen.getByLabelText('Highlight buildings listed in the register'))
  expect(screen.getByTestId('map-show-registry').textContent).toBe('true')
})

// Szara mapa wyglada tak, jakby nie bylo zadnych zgloszen — legenda musi powiedziec, ze to
// stan przelacznika, a nie stan rejestru.
it('makes the legend admit that the highlight is off', async () => {
  stubApi()

  render(<App />)
  expect(screen.queryByText(/Register highlighting is off/)).toBeNull()

  fireEvent.click(screen.getByLabelText('Highlight buildings listed in the register'))

  expect(screen.getByText(/no red does not mean nobody reported anything/)).toBeDefined()
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

/** Skan i klikniecie w przycisk analizy — te same trzy ruchy powtarzaja sie w testach modelu. */
async function scanAndAnalyse() {
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  fireEvent.click(await screen.findByText('Analyse roofs with the model'))
  return await screen.findByTestId('suspected-not-listed')
}

// Model kosztuje kilka sekund i ma twarde limity, wiec nie wolno go wolac samym zaznaczeniem.
it('does not call the model until the user asks for it', async () => {
  const fetchStub = stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  await screen.findByText('47%')

  expect(fetchStub.mock.calls.some((call) => String(call[0]).includes('/api/area/analyze'))).toBe(false)
  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('brak')
})

it('shows the model result and hands the map only the roofs above the threshold', async () => {
  const fetchStub = stubApi()

  render(<App />)
  const leading = await scanAndAnalyse()

  expect(leading.textContent).toBe('1')
  // 42 i 77 sa powyzej progu 0,5; 99 z ocena 0,31 nie jest podejrzeniem i nie trafia na mape.
  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('42,77')
  expect(fetchStub.mock.calls.some((call) => String(call[0]).includes('/api/area/analyze'))).toBe(true)
})

/** Suwak progu w panelu — szukany po etykiecie, tak jak znalazlby go czytnik ekranu. */
function thresholdSlider(): HTMLInputElement {
  return screen.getByLabelText('Suspicion threshold') as HTMLInputElement
}

/**
 * Najwazniejsza zgodnosc w calej tej funkcji: liczba „niezgloszonych z flaga" w panelu i liczba
 * pomaranczowych obrysow na mapie musza pochodzic z tego samego progu. Inaczej panel opisywalby
 * inne dachy, niz widac na ekranie.
 */
it('recounts the panel and the map from the same threshold', async () => {
  stubApi()

  render(<App />)
  await scanAndAnalyse()
  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('42,77')

  fireEvent.change(thresholdSlider(), { target: { value: '0.3' } })

  // 99 (0,31) wchodzi do flagi razem z pozostalymi dwoma — panel i mapa mowia to samo.
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('2')
  expect(screen.getByText('3 (100%)')).toBeDefined()
  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('42,77,99')

  fireEvent.change(thresholdSlider(), { target: { value: '0.75' } })

  // Powyzej 0,75 zostaje sam 77, ktory jest zgloszony, wiec liczba prowadzaca spada do zera.
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('0')
  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('77')
})

it('keeps the model default visible once the threshold is moved', async () => {
  stubApi()

  render(<App />)
  await scanAndAnalyse()
  expect(screen.queryByText(/Model default/)).toBeNull()

  fireEvent.change(thresholdSlider(), { target: { value: '0.25' } })

  expect(screen.getByText('Model default: 50%')).toBeDefined()
})

// Prog nalezy do wyniku, nie do sesji: nowa ocena zaczyna sie od progu, przy ktorym backend
// policzyl swoje statystyki.
it('starts a new analysis from the threshold the backend reported', async () => {
  stubApi()

  render(<App />)
  await scanAndAnalyse()
  fireEvent.change(thresholdSlider(), { target: { value: '0.9' } })
  expect(thresholdSlider().value).toBe('0.9')

  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  fireEvent.click(await screen.findByText('Analyse roofs with the model'))
  await screen.findByTestId('suspected-not-listed')

  expect(thresholdSlider().value).toBe('0.5')
  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('42,77')
})

it('shows the model error exactly as the backend worded it', async () => {
  stubApi({ analysis: [503, { detail: 'The model is not responding. Try again in a moment.' }] })

  render(<App />)
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('narysuj prostokat'))
  fireEvent.click(await screen.findByText('Analyse roofs with the model'))

  expect(await screen.findByText('The model is not responding. Try again in a moment.')).toBeDefined()
  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('brak')
})

// Pomaranczowe obrysy bez panelu, ktory je tlumaczy, zostalyby na mapie jako kolor bez zdania.
it('drops the model result together with the scan panel', async () => {
  stubApi()

  render(<App />)
  await scanAndAnalyse()

  fireEvent.click(screen.getByLabelText('Close'))

  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('brak')
  expect(screen.queryByTestId('suspected-not-listed')).toBeNull()
})

it('clears the previous analysis as soon as the user starts a new selection', async () => {
  stubApi()

  render(<App />)
  await scanAndAnalyse()

  fireEvent.click(screen.getByText('Select'))

  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('brak')
  expect(screen.queryByTestId('suspected-not-listed')).toBeNull()
})

// Karta budynku zaslania panel skanu, ale nie uniewaznia oceny — obrysy zostaja na mapie.
it('keeps the model result on the map after the user opens a building', async () => {
  stubApi()

  render(<App />)
  await scanAndAnalyse()
  fireEvent.click(screen.getByText('Parcel 142511_2.0012.2.2077/21'))
  await screen.findByText(/141210_5\.0017\.105\/1/)

  expect(screen.getByTestId('map-suspected-roofs').textContent).toBe('42,77')
})

it('explains an empty map instead of leaving it looking broken', async () => {
  stubApi()

  render(<App />)
  fireEvent.click(screen.getByText('oddal'))

  // Calego zdania pilnuje ZoomHint.test.tsx; tutaj chodzi tylko o to, ze podpowiedz sie pokazala.
  expect(await screen.findByText(/Zoom in/)).toBeDefined()
})
