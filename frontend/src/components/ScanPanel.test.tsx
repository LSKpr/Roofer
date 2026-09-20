import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { AreaScan, AreaStats, ListedBuilding } from '../api/client'
import { ScanPanel } from './ScanPanel'

/** Liczby z prawdziwego skanu bboxa 2×2 km pod Zwoleniem. */
function someStats(overrides: Partial<AreaStats> = {}): AreaStats {
  return {
    total: 1338,
    listed: 624,
    notListed: 714,
    listedShare: 0.4664,
    roofAreaM2: 158292.7,
    listedRoofAreaM2: 60558.1,
    registryRecords: 681,
    ...overrides,
  }
}

function aListedBuilding(overrides: Partial<ListedBuilding> = {}): ListedBuilding {
  return {
    id: 101,
    areaM2: 148.6,
    centroid: { lng: 21.591, lat: 51.361 },
    nrDzialki: '142509_2.0012.1417/2',
    ...overrides,
  }
}

function aScan(overrides: Partial<AreaScan> = {}): AreaScan {
  return {
    stats: someStats(),
    listedBuildings: [aListedBuilding()],
    truncated: false,
    areaKm2: 4.012,
    ...overrides,
  }
}

function renderPanel(scan: AreaScan | null, handlers: { onClose?: () => void; onPickBuilding?: (id: number) => void } = {}) {
  return render(
    <ScanPanel
      scan={scan}
      loading={false}
      error={null}
      onClose={handlers.onClose ?? (() => {})}
      onPickBuilding={handlers.onPickBuilding ?? (() => {})}
    />,
  )
}

it('prowadzi udzialem zgloszonych w procentach i surowymi liczbami pod nim', () => {
  renderPanel(aScan())

  expect(screen.getByText('47%')).toBeDefined()
  expect(screen.getByText('Udział zgłoszonych w rejestrze')).toBeDefined()
  expect(screen.getByText('624 z 1338 budynków')).toBeDefined()
})

it('rysuje pasek udzialu szerokoscia w procentach, bez biblioteki do wykresow', () => {
  renderPanel(aScan())

  const bar = screen.getByTestId('listed-share-bar')

  expect(bar.getAttribute('style')).toContain('width: 46.6%')
  expect(bar.className).toContain('bg-listed')
})

it('skaluje pasek razem z udzialem i nigdy nie wychodzi poza 100%', () => {
  renderPanel(aScan({ stats: someStats({ listedShare: 0, listed: 0, notListed: 1338 }) }))
  // 0.0% skraca sie w CSS do 0% — pasek zwezony do zera, nie brak szerokosci.
  expect(screen.getByTestId('listed-share-bar').getAttribute('style')).toContain('width: 0%')

  renderPanel(aScan({ stats: someStats({ listedShare: 1, listed: 1338, notListed: 0 }) }))
  const bars = screen.getAllByTestId('listed-share-bar')
  expect(bars[1].getAttribute('style')).toContain('width: 100%')
})

it('pokazuje wszystkie pary etykieta/wartosc z polskim formatem liczb', () => {
  renderPanel(aScan())

  expect(screen.getByText('Powierzchnia zaznaczenia')).toBeDefined()
  expect(screen.getByText('4,0 km²')).toBeDefined()
  expect(screen.getByText('Budynki w obszarze')).toBeDefined()
  expect(screen.getByText('1338')).toBeDefined()
  expect(screen.getByText('Zgłoszone')).toBeDefined()
  expect(screen.getByText('624')).toBeDefined()
  expect(screen.getByText('Niezgłoszone')).toBeDefined()
  expect(screen.getByText('714')).toBeDefined()
  expect(screen.getByText('Powierzchnia dachów')).toBeDefined()
  expect(screen.getByText('158 293 m²')).toBeDefined()
  expect(screen.getByText('Powierzchnia dachów zgłoszonych')).toBeDefined()
  expect(screen.getByText('60 558 m²')).toBeDefined()
  expect(screen.getByText('Rekordy rejestru w obszarze')).toBeDefined()
  expect(screen.getByText('681')).toBeDefined()
})

it('wypisuje zgloszone budynki z numerem dzialki i powierzchnia', () => {
  renderPanel(
    aScan({
      listedBuildings: [aListedBuilding(), aListedBuilding({ id: 202, nrDzialki: null, areaM2: 96.4 })],
    }),
  )

  expect(screen.getByText('Działka 142509_2.0012.1417/2')).toBeDefined()
  expect(screen.getByText('149 m²')).toBeDefined()
  expect(screen.getByText('Bez numeru działki')).toBeDefined()
  expect(screen.getByText('96 m²')).toBeDefined()
})

it('woła onPickBuilding z identyfikatorem klikniętego wiersza', () => {
  const onPickBuilding = vi.fn()
  renderPanel(
    aScan({
      listedBuildings: [aListedBuilding({ id: 101 }), aListedBuilding({ id: 202, nrDzialki: '99/7' })],
    }),
    { onPickBuilding },
  )

  fireEvent.click(screen.getByText('Działka 99/7'))

  expect(onPickBuilding).toHaveBeenCalledTimes(1)
  expect(onPickBuilding).toHaveBeenCalledWith(202)
})

it('klikalny jest caly wiersz listy, a nie tekst w nim', () => {
  renderPanel(aScan())

  const rows = screen.getAllByRole('button').filter((node) => node.textContent?.includes('Działka'))

  expect(rows).toHaveLength(1)
  expect(rows[0].getAttribute('type')).toBe('button')
})

it('mowi, ze lista jest przycieta, a statystyki liczą cały obszar', () => {
  renderPanel(
    aScan({
      listedBuildings: [aListedBuilding(), aListedBuilding({ id: 202 })],
      truncated: true,
    }),
  )

  expect(screen.getByText(/widać 2 pozycje z 624 zgłoszonych budynków/)).toBeDefined()
  expect(screen.getByText(/Statystyki powyżej liczą cały zaznaczony obszar/)).toBeDefined()
})

it('odmienia liczbe pozycji w zdaniu o przycieciu', () => {
  const many = Array.from({ length: 5 }, (_, index) => aListedBuilding({ id: 300 + index }))

  renderPanel(aScan({ listedBuildings: many, truncated: true }))

  expect(screen.getByText(/widać 5 pozycji z 624 zgłoszonych budynków/)).toBeDefined()
})

it('nie wspomina o przycieciu, gdy lista jest kompletna', () => {
  renderPanel(aScan())

  expect(screen.queryByText(/przycięta/)).toBeNull()
})

it('zamiast pustych zer mowi, ze w obszarze nie ma budynkow', () => {
  renderPanel(
    aScan({
      stats: someStats({ total: 0, listed: 0, notListed: 0, listedShare: 0, roofAreaM2: 0, listedRoofAreaM2: 0, registryRecords: 0 }),
      listedBuildings: [],
    }),
  )

  expect(screen.getByText('W tym obszarze nie ma budynków z OpenStreetMap.')).toBeDefined()
  expect(screen.getByText('4,0 km²')).toBeDefined()
  expect(screen.queryByText('Zgłoszone')).toBeNull()
  expect(screen.queryByText('0%')).toBeNull()
})

it('informuje o trwajacym skanie', () => {
  render(<ScanPanel scan={null} loading={true} error={null} onClose={() => {}} onPickBuilding={() => {}} />)

  expect(screen.getByText('Skanuję obszar…')).toBeDefined()
})

it('pokazuje blad backendu bez przerabiania go i zostawia dzialajace zamkniecie', () => {
  const onClose = vi.fn()
  const message = 'Obszar ma 41 km2, a maksimum to 25 km2 — zaznacz mniejszy fragment.'
  render(
    <ScanPanel scan={null} loading={false} error={message} onClose={onClose} onPickBuilding={() => {}} />,
  )

  expect(screen.getByText(message)).toBeDefined()

  fireEvent.click(screen.getByLabelText('Zamknij'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('wola onClose po kliknieciu w zamkniecie wyniku', () => {
  const onClose = vi.fn()
  renderPanel(aScan(), { onClose })

  fireEvent.click(screen.getByLabelText('Zamknij'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('nie renderuje nic bez wyniku, bledu i skanowania', () => {
  const view = renderPanel(null)

  expect(view.container.firstChild).toBeNull()
})

it('konczy zastrzezeniem o niekompletnosci rejestru', () => {
  renderPanel(aScan())

  expect(screen.getByText(/Rejestr GeoAzbest jest niekompletny/)).toBeDefined()
  expect(screen.getByText(/nie jest dowodem, że dach jest czysty/)).toBeDefined()
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const view = renderPanel(aScan({ truncated: true }))

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/wykryto|brak azbestu|bezpieczny|czysty dach/i)
})
