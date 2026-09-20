import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Building, RegistryMatch, RoofAnalysis } from '../api/client'
import { BuildingPanel } from './BuildingPanel'

const MOCK_ANALYSIS: RoofAnalysis = {
  source: 'mock',
  verdict: 'suspected',
  probability: 0.56,
  modelName: null,
  note: 'Wynik demonstracyjny, bez modelu ML.',
}

/** Karta sama pobiera analize pokrycia, wiec kazdy render dotyka sieci. */
function stubAnalysis(analysis: RoofAnalysis = MOCK_ANALYSIS) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, json: async () => analysis }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function aMatch(overrides: Partial<RegistryMatch> = {}): RegistryMatch {
  return {
    sourceId: 'GA-4711',
    nrDzialki: '141704_2.0012.1417/2',
    recordAreaM2: 98.4,
    overlapM2: 61.2,
    shareBuilding: 0.37,
    shareRecord: 0.62,
    ...overrides,
  }
}

function aBuilding(overrides: Partial<Building> = {}): Building {
  return {
    id: 7,
    kind: 'building',
    osmType: 'house',
    name: 'Stodoła',
    areaM2: 165.4,
    centroid: { lng: 21.083124, lat: 51.250471 },
    status: 'not_listed',
    registryMatches: [],
    otherIntersecting: 0,
    ...overrides,
  }
}

function renderPanel(building: Building | null, onClose: () => void = () => {}) {
  return render(<BuildingPanel building={building} loading={false} error={null} onClose={onClose} />)
}

it('pokazuje numer dzialki i udzialy przekrycia dla budynku zgloszonego', () => {
  renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch()] }))

  expect(screen.getByText('Zgłoszony w rejestrze')).toBeDefined()
  expect(screen.getByText('Działka 141704_2.0012.1417/2')).toBeDefined()
  expect(screen.getByText('61 m²')).toBeDefined()
  expect(screen.getByText('37%')).toBeDefined()
  expect(screen.getByText('62%')).toBeDefined()
})

it('podaje powierzchnie bez czesci dziesietnej, centroid i identyfikator OSM', () => {
  // Identyfikator budynku JEST identyfikatorem z OSM, wiec ten sam numer stoi w wierszu
  // „OpenStreetMap" — dawny klucz z sekwencji bazy nie prowadzil do niczego na zewnatrz.
  renderPanel(aBuilding({ id: 382845106 }))

  expect(screen.getByText('165 m²')).toBeDefined()
  expect(screen.getByText('21.08312, 51.25047')).toBeDefined()
  expect(screen.getByText('382845106')).toBeDefined()
})

it('pokazuje identyfikator zrodla, gdy rekord nie ma numeru dzialki', () => {
  renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch({ nrDzialki: null })] }))

  expect(screen.getByText('Rekord GA-4711')).toBeDefined()
})

it('dla niezgloszonego budynku dodaje zastrzezenie i nie pokazuje listy rekordow', () => {
  renderPanel(aBuilding({ status: 'not_listed', registryMatches: [aMatch()] }))

  expect(screen.getByText('Niezgłoszony')).toBeDefined()
  expect(screen.getByText(/nie jest dowód, że dach jest czysty/)).toBeDefined()
  expect(screen.queryByText(/Rekordy rejestru/)).toBeNull()
  expect(screen.queryByText(/Działka/)).toBeNull()
})

it('wyjasnia rekordy, ktore przecinaja budynek, ale nie spelnily reguly dopasowania', () => {
  renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch()], otherIntersecting: 3 }))

  expect(screen.getByText(/3 rekordy rejestru, które nie spełniły reguły dopasowania/)).toBeDefined()
  expect(screen.getByText(/obrysy działek, nie dachów/)).toBeDefined()
})

it('nie wspomina o odrzuconych rekordach, gdy ich nie ma', () => {
  renderPanel(aBuilding({ otherIntersecting: 0 }))

  expect(screen.queryByText(/reguły dopasowania/)).toBeNull()
})

it('nazywa budynek bez nazwy jego rodzajem po polsku, a nie wartoscia fclass', () => {
  // `kind` to zawsze „building", wiec w naglowku karty wygladalo jak awaria.
  renderPanel(aBuilding({ name: '  ', kind: 'building', osmType: 'farm_auxiliary' }))
  expect(screen.getByText('budynek gospodarczy')).toBeDefined()

  renderPanel(aBuilding({ name: null, kind: 'building', osmType: null }))
  expect(screen.getByText('Budynek bez nazwy')).toBeDefined()
})

it('informuje o wczytywaniu', () => {
  render(<BuildingPanel building={null} loading={true} error={null} onClose={() => {}} />)

  expect(screen.getByText('Wczytuję szczegóły…')).toBeDefined()
})

it('pokazuje blad razem z dzialajacym przyciskiem zamkniecia', () => {
  const onClose = vi.fn()
  render(<BuildingPanel building={null} loading={false} error="Backend odpowiedział kodem 500" onClose={onClose} />)

  expect(screen.getByText('Backend odpowiedział kodem 500')).toBeDefined()

  fireEvent.click(screen.getByLabelText('Zamknij'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('wola onClose po kliknieciu w zamkniecie karty', () => {
  const onClose = vi.fn()
  renderPanel(aBuilding(), onClose)

  fireEvent.click(screen.getByLabelText('Zamknij'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('nie renderuje nic bez budynku, bledu i wczytywania', () => {
  const view = renderPanel(null)

  expect(view.container.firstChild).toBeNull()
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const view = renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch()] }))

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/wykryto|brak azbestu|bezpieczny/i)
})

it('pokazuje zdjecie dachu zgloszonego budynku razem z atrybucja GUGiK', () => {
  renderPanel(aBuilding({ id: 12, status: 'listed', registryMatches: [aMatch()] }))

  expect(screen.getByAltText(/dachu budynku/i).getAttribute('src')).toContain('/api/buildings/12/roof.png')
  expect(screen.getByText('Ortofotomapa: GUGiK / Geoportal.gov.pl')).toBeDefined()
})

it('pokazuje zdjecie dachu takze dla budynku niezgloszonego', () => {
  renderPanel(aBuilding({ id: 34, status: 'not_listed' }))

  expect(screen.getByAltText(/dachu budynku/i).getAttribute('src')).toContain('/api/buildings/34/roof.png')
})

it('zamienia niedostepne ortofoto na komunikat, nie na pusta ramke', () => {
  renderPanel(aBuilding())

  fireEvent.error(screen.getByAltText(/dachu budynku/i))

  expect(screen.getByText('Ortofotomapa niedostępna')).toBeDefined()
})

it('oznacza status kwadratowa kropka w kolorze rejestru, a nie kolorowa plakietka', () => {
  renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch()] }))
  expect(screen.getByTestId('status-dot').className).toContain('bg-listed')

  renderPanel(aBuilding({ status: 'not_listed' }))
  const dots = screen.getAllByTestId('status-dot')
  expect(dots[1].className).toContain('bg-not-listed')
  expect(dots[1].className).not.toContain('rounded')
})

it('pokazuje analize pokrycia dachu i ostrzega, ze wynik jest demonstracyjny', async () => {
  stubAnalysis()

  renderPanel(aBuilding({ id: 12 }))

  expect(await screen.findByText(/Podejrzenie pokrycia falistego/)).toBeDefined()
  expect(screen.getByText('56%')).toBeDefined()
  // Bez tego ostrzezenia wymyslona liczba wygladalaby jak wynik modelu.
  expect(screen.getByText(/Wynik demonstracyjny · model niepodłączony/)).toBeDefined()
})

it('pokazuje rodzaj budynku z OSM po polsku, razem z surowym tagiem', () => {
  stubAnalysis()

  renderPanel(aBuilding({ osmType: 'outbuilding' }))

  expect(screen.getByText('Rodzaj (OSM)')).toBeDefined()
  expect(screen.getByText('budynek gospodarczy · outbuilding')).toBeDefined()
})

it('nie pokazuje wiersza rodzaju, gdy OSM go nie podaje', () => {
  stubAnalysis()

  renderPanel(aBuilding({ osmType: null }))

  expect(screen.queryByText('Rodzaj (OSM)')).toBeNull()
})
