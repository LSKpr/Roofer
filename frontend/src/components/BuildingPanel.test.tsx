import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Building, RegistryMatch, RoofAnalysis } from '../api/client'
import { buildingTypeLabel, buildingTypeName } from '../lib/osmBuildingType'
import { BuildingPanel } from './BuildingPanel'

const MOCK_ANALYSIS: RoofAnalysis = {
  source: 'mock',
  verdict: 'suspected',
  probability: 0.56,
  modelName: null,
  note: 'Demonstration result, no ML model.',
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

  expect(screen.getByText('Listed in the register')).toBeDefined()
  expect(screen.getByText('Parcel 141704_2.0012.1417/2')).toBeDefined()
  expect(screen.getByText('61 m²')).toBeDefined()
  expect(screen.getByText('37%')).toBeDefined()
  expect(screen.getByText('62%')).toBeDefined()
})

it('podaje powierzchnie bez czesci dziesietnej i z angielskim separatorem tysiecy, centroid i identyfikator OSM', () => {
  // Identyfikator budynku JEST identyfikatorem z OSM, wiec ten sam numer stoi w wierszu
  // „OpenStreetMap" — dawny klucz z sekwencji bazy nie prowadzil do niczego na zewnatrz.
  renderPanel(aBuilding({ id: 382845106, areaM2: 158292.7 }))

  expect(screen.getByText('158,293 m²')).toBeDefined()
  expect(screen.getByText('21.08312, 51.25047')).toBeDefined()
  expect(screen.getByText('382845106')).toBeDefined()
})

it('pokazuje identyfikator zrodla, gdy rekord nie ma numeru dzialki', () => {
  renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch({ nrDzialki: null })] }))

  expect(screen.getByText('Record GA-4711')).toBeDefined()
})

it('dla niezgloszonego budynku dodaje zastrzezenie i nie pokazuje listy rekordow', () => {
  renderPanel(aBuilding({ status: 'not_listed', registryMatches: [aMatch()] }))

  expect(screen.getByText('Not listed')).toBeDefined()
  expect(screen.getByText(/not proof that the roof is clean/)).toBeDefined()
  expect(screen.queryByText(/Register records/)).toBeNull()
  expect(screen.queryByText(/Parcel/)).toBeNull()
})

it('wyjasnia rekordy, ktore przecinaja budynek, ale nie spelnily reguly dopasowania', () => {
  renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch()], otherIntersecting: 3 }))

  expect(screen.getByText(/3 register records that did not meet the matching rule/)).toBeDefined()
  expect(screen.getByText(/parcel outlines, not roof outlines/)).toBeDefined()
})

it('nie wspomina o odrzuconych rekordach, gdy ich nie ma', () => {
  renderPanel(aBuilding({ otherIntersecting: 0 }))

  expect(screen.queryByText(/matching rule/)).toBeNull()
})

it('nazywa budynek bez nazwy jego rodzajem z OSM, a nie wartoscia fclass', () => {
  // `kind` to zawsze „building", wiec w naglowku karty wygladalo jak awaria. Nazwe rodzaju bierzemy
  // z lib/osmBuildingType, zeby test pilnowal doboru pola, a nie jezyka tamtego slownika.
  renderPanel(aBuilding({ name: '  ', kind: 'building', osmType: 'farm_auxiliary' }))
  expect(screen.getByText(buildingTypeName('farm_auxiliary') ?? '')).toBeDefined()

  renderPanel(aBuilding({ name: null, kind: 'building', osmType: null }))
  expect(screen.getByText('Unnamed building')).toBeDefined()
})

it('informuje o wczytywaniu', () => {
  render(<BuildingPanel building={null} loading={true} error={null} onClose={() => {}} />)

  expect(screen.getByText('Loading details…')).toBeDefined()
})

it('pokazuje blad razem z dzialajacym przyciskiem zamkniecia', () => {
  const onClose = vi.fn()
  render(<BuildingPanel building={null} loading={false} error="Backend responded with status 500" onClose={onClose} />)

  expect(screen.getByText('Backend responded with status 500')).toBeDefined()

  fireEvent.click(screen.getByLabelText('Close'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('wola onClose po kliknieciu w zamkniecie karty', () => {
  const onClose = vi.fn()
  renderPanel(aBuilding(), onClose)

  fireEvent.click(screen.getByLabelText('Close'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('nie renderuje nic bez budynku, bledu i wczytywania', () => {
  const view = renderPanel(null)

  expect(view.container.firstChild).toBeNull()
})

/** Twierdzenia, ktorych karta nie ma prawa postawic: ze cos wykryto albo ze dach jest czysty. */
const CLAIM = /detected|asbestos-free|no asbestos|safe|clean/i

/** Jedyne dozwolone „clean" w karcie: zaprzeczone, w zdaniu o budynku spoza rejestru. */
const NOT_PROOF = 'That is not proof that the roof is clean'

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const view = renderPanel(aBuilding({ status: 'listed', registryMatches: [aMatch()] }))

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(CLAIM)
})

it('o niezgloszonym budynku tez nie twierdzi, ze dach jest czysty', () => {
  const view = renderPanel(aBuilding({ status: 'not_listed' }))

  const text = view.container.textContent ?? ''
  // Zaprzeczenie musi padc wprost, wiec straznik wycina dokladnie to jedno zdanie i reszty pilnuje
  // tak samo ostro. Gdyby zdanie znikelo albo zmienilo brzmienie, wyciecie nic nie zabierze —
  // wtedy albo pierwsza asercja upada, albo straznik lapie slowo „clean" w drugiej.
  expect(text).toContain(NOT_PROOF)
  expect(text.replace(NOT_PROOF, '')).not.toMatch(CLAIM)
})

it('pokazuje zdjecie dachu zgloszonego budynku razem z atrybucja GUGiK', () => {
  renderPanel(aBuilding({ id: 12, status: 'listed', registryMatches: [aMatch()] }))

  expect(screen.getByAltText(/roof of building/i).getAttribute('src')).toContain('/api/buildings/12/roof.png')
  expect(screen.getByText('Aerial imagery: GUGiK / Geoportal.gov.pl')).toBeDefined()
})

it('pokazuje zdjecie dachu takze dla budynku niezgloszonego', () => {
  renderPanel(aBuilding({ id: 34, status: 'not_listed' }))

  expect(screen.getByAltText(/roof of building/i).getAttribute('src')).toContain('/api/buildings/34/roof.png')
})

it('zamienia niedostepne ortofoto na komunikat, nie na pusta ramke', () => {
  renderPanel(aBuilding())

  fireEvent.error(screen.getByAltText(/roof of building/i))

  expect(screen.getByText('Aerial imagery unavailable')).toBeDefined()
})

// Karta niczego z tego pola nie liczy — jej cala robota to przepuscic je do podpisu pod kadrem.
it('przepuszcza zrodlo kadru do podpisu pod zdjeciem', () => {
  stubAnalysis()

  renderPanel(aBuilding({ id: 12, roofImage: { source: 'local', gsdM: 0.05, frameM: 12.8, acquiredOn: '2023-12-05' } }))

  expect(screen.getByText(/Flown on 5 December 2023/)).toBeDefined()
  expect(screen.getByText(/fixed 12\.8 m square/)).toBeDefined()
})

it('przy kadrze z WMS-a nie pokazuje zadnej daty nalotu', () => {
  stubAnalysis()

  const view = renderPanel(aBuilding({ roofImage: { source: 'wms', gsdM: null, frameM: null, acquiredOn: null } }))

  expect(screen.getByText(/during the aerial survey/)).toBeDefined()
  expect(view.container.textContent ?? '').not.toMatch(/December|Flown on|fixed 12/)
})

it('bez tego pola karta nie wymysla daty nalotu', () => {
  stubAnalysis()

  const view = renderPanel(aBuilding())

  expect(screen.getByText(/during the aerial survey/)).toBeDefined()
  expect(view.container.textContent ?? '').not.toMatch(/December|Flown on|fixed 12/)
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

  expect(await screen.findByText(/Possible corrugated grey covering/)).toBeDefined()
  expect(screen.getByText('56%')).toBeDefined()
  // Bez tego ostrzezenia wymyslona liczba wygladalaby jak wynik modelu.
  expect(screen.getByText(/Demonstration result · no model connected/)).toBeDefined()
})

it('pokazuje rodzaj budynku z OSM razem z surowym tagiem', () => {
  stubAnalysis()

  renderPanel(aBuilding({ osmType: 'farm_auxiliary' }))

  // Etykieta rodzaju siedzi w lib/osmBuildingType i przy nieoczywistym tagu doklada go obok nazwy;
  // karta ma pokazac ja w calosci, bo po surowym tagu weryfikuje sie dane w OSM.
  const label = buildingTypeLabel('farm_auxiliary') ?? ''
  expect(label).toContain('farm_auxiliary')
  expect(screen.getByText('Type (OSM)')).toBeDefined()
  expect(screen.getByText(label)).toBeDefined()
})

it('nie pokazuje wiersza rodzaju, gdy OSM go nie podaje', () => {
  stubAnalysis()

  renderPanel(aBuilding({ osmType: null }))

  expect(screen.queryByText('Type (OSM)')).toBeNull()
})
