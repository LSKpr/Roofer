import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { AreaAnalysis, AreaAnalysisStats, AreaModelLimits, AreaScan, AreaStats, ListedBuilding } from '../api/client'
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

/** Prawdziwe limity tamtego serwisu: 100 budynkow i 4 km2 na zadanie. */
const MODEL_LIMITS: AreaModelLimits = { maxBuildings: 100, maxAreaKm2: 4 }

/** Skan, ktory miesci sie w limitach modelu: 74 budynki pod Zwoleniem. */
function aSmallScan(overrides: Partial<AreaScan> = {}): AreaScan {
  return aScan({
    stats: someStats({
      total: 74,
      listed: 3,
      notListed: 71,
      listedShare: 0.0405,
      roofAreaM2: 9123.4,
      listedRoofAreaM2: 402.1,
      registryRecords: 4,
    }),
    areaKm2: 0.6,
    ...overrides,
  })
}

/** Wynik modelu z tego samego przebiegu: 64 budynki z ocena, 10 bez. */
const MODEL_STATS: AreaAnalysisStats = {
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
}

type AnalysisOverrides = Omit<Partial<AreaAnalysis>, 'stats'> & { stats?: Partial<AreaAnalysisStats> }

function anAnalysis(overrides: AnalysisOverrides = {}): AreaAnalysis {
  const { stats, ...rest } = overrides
  return { stats: { ...MODEL_STATS, ...stats }, buildings: [], truncated: false, ...rest }
}

type PanelOptions = {
  onClose?: () => void
  onPickBuilding?: (id: number) => void
  loading?: boolean
  error?: string | null
  analysis?: AreaAnalysis | null
  analysisLoading?: boolean
  analysisError?: string | null
  onAnalyse?: () => void
  modelLimits?: AreaModelLimits | null
}

function renderPanel(scan: AreaScan | null, options: PanelOptions = {}) {
  return render(
    <ScanPanel
      scan={scan}
      loading={options.loading ?? false}
      error={options.error ?? null}
      onClose={options.onClose ?? (() => {})}
      onPickBuilding={options.onPickBuilding ?? (() => {})}
      analysis={options.analysis ?? null}
      analysisLoading={options.analysisLoading ?? false}
      analysisError={options.analysisError ?? null}
      onAnalyse={options.onAnalyse ?? (() => {})}
      modelLimits={'modelLimits' in options ? (options.modelLimits ?? null) : MODEL_LIMITS}
    />,
  )
}

/** Przycisk analizy jest jedynym przyciskiem z ta etykieta, wiec szukamy go po niej. */
function analyseButton(): HTMLButtonElement {
  return screen.getByText('Analyse roofs with the model') as HTMLButtonElement
}

it('prowadzi udzialem zgloszonych w procentach i surowymi liczbami pod nim', () => {
  renderPanel(aScan())

  expect(screen.getByText('47%')).toBeDefined()
  expect(screen.getByText('Share listed in the register')).toBeDefined()
  expect(screen.getByText('624 of 1,338 buildings')).toBeDefined()
})

/** Po angielsku zostaje jedna regula: 1 building, kazda inna liczba buildings. */
it('pisze „building" tylko przy jednym budynku', () => {
  renderPanel(aScan({ stats: someStats({ total: 1, listed: 1, notListed: 0, listedShare: 1 }) }))
  expect(screen.getByText('1 of 1 building')).toBeDefined()

  renderPanel(aScan({ stats: someStats({ total: 2, listed: 1, notListed: 1, listedShare: 0.5 }) }))
  expect(screen.getByText('1 of 2 buildings')).toBeDefined()
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

it('pokazuje wszystkie pary etykieta/wartosc z angielskim formatem liczb', () => {
  renderPanel(aScan())

  expect(screen.getByText('Selection area')).toBeDefined()
  expect(screen.getByText('4.0 km²')).toBeDefined()
  expect(screen.getByText('Buildings in the area')).toBeDefined()
  expect(screen.getByText('1,338')).toBeDefined()
  expect(screen.getByText('Listed')).toBeDefined()
  expect(screen.getByText('624')).toBeDefined()
  expect(screen.getByText('Not listed')).toBeDefined()
  expect(screen.getByText('714')).toBeDefined()
  expect(screen.getByText('Roof area')).toBeDefined()
  expect(screen.getByText('158,293 m²')).toBeDefined()
  expect(screen.getByText('Roof area of listed buildings')).toBeDefined()
  expect(screen.getByText('60,558 m²')).toBeDefined()
  expect(screen.getByText('Register records in the area')).toBeDefined()
  expect(screen.getByText('681')).toBeDefined()
})

it('wypisuje zgloszone budynki z numerem dzialki i powierzchnia', () => {
  renderPanel(
    aScan({
      listedBuildings: [aListedBuilding(), aListedBuilding({ id: 202, nrDzialki: null, areaM2: 96.4 })],
    }),
  )

  expect(screen.getByText('Parcel 142509_2.0012.1417/2')).toBeDefined()
  expect(screen.getByText('149 m²')).toBeDefined()
  expect(screen.getByText('No parcel number')).toBeDefined()
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

  fireEvent.click(screen.getByText('Parcel 99/7'))

  expect(onPickBuilding).toHaveBeenCalledTimes(1)
  expect(onPickBuilding).toHaveBeenCalledWith(202)
})

it('klikalny jest caly wiersz listy, a nie tekst w nim', () => {
  renderPanel(aScan())

  const rows = screen.getAllByRole('button').filter((node) => node.textContent?.includes('Parcel'))

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

  expect(screen.getByText(/showing 2 of 624 listed buildings/)).toBeDefined()
  expect(screen.getByText(/The statistics above cover the whole selected area/)).toBeDefined()
})

// Liczba w zdaniu ma byc dlugoscia widocznej listy, a nie statystyka z backendu — inaczej
// zdanie o przycieciu tlumaczyloby sie z liczby, ktorej na ekranie nie widac.
it('liczy pokazane pozycje z dlugosci listy, a nie ze statystyk', () => {
  const many = Array.from({ length: 5 }, (_, index) => aListedBuilding({ id: 300 + index }))

  renderPanel(aScan({ listedBuildings: many, truncated: true }))

  expect(screen.getByText(/showing 5 of 624 listed buildings/)).toBeDefined()
})

it('nie wspomina o przycieciu, gdy lista jest kompletna', () => {
  renderPanel(aScan())

  expect(screen.queryByText(/truncated/)).toBeNull()
})

it('zamiast pustych zer mowi, ze w obszarze nie ma budynkow', () => {
  renderPanel(
    aScan({
      stats: someStats({ total: 0, listed: 0, notListed: 0, listedShare: 0, roofAreaM2: 0, listedRoofAreaM2: 0, registryRecords: 0 }),
      listedBuildings: [],
    }),
  )

  expect(screen.getByText('There are no OpenStreetMap buildings in this area.')).toBeDefined()
  expect(screen.getByText('4.0 km²')).toBeDefined()
  expect(screen.queryByText('Listed')).toBeNull()
  expect(screen.queryByText('0%')).toBeNull()
})

it('informuje o trwajacym skanie', () => {
  renderPanel(null, { loading: true })

  expect(screen.getByText('Scanning the area…')).toBeDefined()
})

it('pokazuje blad backendu bez przerabiania go i zostawia dzialajace zamkniecie', () => {
  const onClose = vi.fn()
  const message = 'Obszar ma 41 km2, a maksimum to 25 km2 — zaznacz mniejszy fragment.'
  renderPanel(null, { error: message, onClose })

  expect(screen.getByText(message)).toBeDefined()

  fireEvent.click(screen.getByLabelText('Close'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('wola onClose po kliknieciu w zamkniecie wyniku', () => {
  const onClose = vi.fn()
  renderPanel(aScan(), { onClose })

  fireEvent.click(screen.getByLabelText('Close'))

  expect(onClose).toHaveBeenCalledTimes(1)
})

it('nie renderuje nic bez wyniku, bledu i skanowania', () => {
  const view = renderPanel(null)

  expect(view.container.firstChild).toBeNull()
})

it('konczy zastrzezeniem o niekompletnosci rejestru', () => {
  renderPanel(aScan())

  expect(screen.getByText(/The GeoAzbest register is incomplete/)).toBeDefined()
  expect(screen.getByText(/not proof that the roof is clean/)).toBeDefined()
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const view = renderPanel(aScan({ truncated: true }))

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)
})

// Ten sam straznik slownictwa, ale na sekcji modelu: to ona najlatwiej zsunelaby sie
// z „model cos widzi na zdjeciu" na „wykryto azbest".
it('nie uzywa slownictwa sugerujacego pomiar azbestu takze w sekcji modelu', () => {
  const view = renderPanel(aSmallScan(), { analysis: anAnalysis({ truncated: true }) })

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)
})

it('daje przycisk analizy dopiero wtedy, gdy jest wynik skanu', () => {
  renderPanel(null, { loading: true })
  expect(screen.queryByText('Analyse roofs with the model')).toBeNull()

  renderPanel(aSmallScan())

  expect(analyseButton().disabled).toBe(false)
})

// Liczbe budynkow znamy z wyniku skanu, wiec powod odmowy stoi przy przycisku, zanim
// uzytkownik w niego kliknie i zanim model odeslalby 400.
it('wylacza przycisk i podaje liczbe budynkow, gdy obszar przekracza limit modelu', () => {
  const onAnalyse = vi.fn()
  renderPanel(aScan(), { onAnalyse })

  expect(analyseButton().disabled).toBe(true)
  expect(screen.getByText('The model accepts up to 100 buildings; this area has 1,338.')).toBeDefined()

  fireEvent.click(analyseButton())
  expect(onAnalyse).not.toHaveBeenCalled()
})

it('wylacza przycisk takze wtedy, gdy za duza jest sama powierzchnia', () => {
  renderPanel(aSmallScan({ areaKm2: 6.3 }))

  expect(analyseButton().disabled).toBe(true)
  expect(screen.getByText('The model accepts up to 4.0 km²; this selection is 6.3 km².')).toBeDefined()
})

// Limity zna backend. Gdy ich nie poda, front nie zgaduje wlasnych: pyta i pokazuje odpowiedz.
it('nie blokuje przycisku, gdy backend nie podal limitow modelu', () => {
  renderPanel(aScan(), { modelLimits: null })

  expect(analyseButton().disabled).toBe(false)
  expect(screen.queryByText(/The model accepts up to/)).toBeNull()
})

it('wola onAnalyse po kliknieciu w przycisk', () => {
  const onAnalyse = vi.fn()
  renderPanel(aSmallScan(), { onAnalyse })

  fireEvent.click(analyseButton())

  expect(onAnalyse).toHaveBeenCalledTimes(1)
})

// Zadanie idzie kilka sekund — bez tego zdania panel wyglada na zepsuty.
it('mowi, ze analiza trwa, i ile dachow obejmuje', () => {
  renderPanel(aSmallScan(), { analysisLoading: true })

  expect(screen.getByText('Analysing 74 roofs…')).toBeDefined()
  expect(screen.queryByText('Analyse roofs with the model')).toBeNull()
})

it('odmienia liczbe dachow w stanie pracy', () => {
  renderPanel(aSmallScan({ stats: someStats({ total: 1, listed: 0, notListed: 1, listedShare: 0 }) }), {
    analysisLoading: true,
  })

  expect(screen.getByText('Analysing 1 roof…')).toBeDefined()
})

// Najwazniejsza liczba w calej aplikacji: dachy, ktorych nikt nie zglosil, a model cos na nich widzi.
it('prowadzi liczba niezgloszonych dachow z flaga modelu', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  const leading = screen.getByTestId('suspected-not-listed')

  expect(leading.textContent).toBe('14')
  expect(leading.className).toContain('font-display')
  expect(screen.getByText('Not in the register, flagged by the model')).toBeDefined()
})

// Kropka nosi ten sam token, ktorym mapa maluje obrysy — zdanie „orange marks…" ma sie do czego
// odniesc, a czerwien zostaje przy rejestrze.
it('znaczy liczbe prowadzaca kolorem podejrzenia, nie czerwienia rejestru', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  const dot = screen.getByTestId('suspected-dot')

  expect(dot.className).toContain('bg-suspected')
  expect(dot.className).not.toContain('bg-listed')
})

it('pokazuje wszystkie liczby modelu jako pary etykieta/wartosc', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByText('Roofs analysed')).toBeDefined()
  expect(screen.getByText('64')).toBeDefined()
  expect(screen.getByText('No result from the model')).toBeDefined()
  expect(screen.getByText('10')).toBeDefined()
  expect(screen.getByText('Flagged by the model')).toBeDefined()
  expect(screen.getByText('16 (25%)')).toBeDefined()
  expect(screen.getByText('Flagged and already listed')).toBeDefined()
  expect(screen.getByText('2')).toBeDefined()
  expect(screen.getByText('Listed but not flagged')).toBeDefined()
  expect(screen.getByText('1')).toBeDefined()
  expect(screen.getByText('Roof area flagged')).toBeDefined()
  expect(screen.getByText('2,432 m²')).toBeDefined()
  expect(screen.getByText('Model')).toBeDefined()
  expect(screen.getByText('70b702')).toBeDefined()
})

it('wycisza nazwe modelu, bo to identyfikator, a nie liczba do czytania', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByText('70b702').className).toContain('text-ink-faint')
})

it('mowi, czego pomaranczowy nie znaczy, i podaje skutecznosc modelu', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByText('Orange marks what the model sees on a photo, not a fact from the register.')).toBeDefined()
  expect(
    screen.getByText(
      'The model reports 77% accuracy and 63% asbestos recall, so treat a flag as a hint for an inspection.',
    ),
  ).toBeDefined()
})

// Brak oceny to trzeci stan, nie ocena „nic nie widac".
it('tlumaczy, ze brak oceny to nie to samo, co dach bez pokrycia', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByText(/10 roofs got no score \(too little detail, greenery, or no imagery\)/)).toBeDefined()
  expect(screen.getByText(/not the same as a roof the model saw nothing on/)).toBeDefined()
})

it('nie pisze o braku ocen, gdy wszystkie dachy dostaly ocene', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis({ stats: { noResult: 0 } }) })

  expect(screen.queryByText(/got no score/)).toBeNull()
})

// Zgloszony dach bez flagi modelu wyglada na odwolanie zgloszenia — i to jest najgrozniejsze
// nieporozumienie w tej sekcji.
it('nie pozwala odczytac braku flagi u zgloszonego dachu jako zniknięcia azbestu', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByText(/1 listed roof was not flagged by the model/)).toBeDefined()
  expect(screen.getByText(/That does not mean the asbestos is gone/)).toBeDefined()
  expect(screen.getByText(/the model may not recognise it, or the roof may look different from above/)).toBeDefined()
})

it('odmienia zdanie o zgloszonych dachach bez flagi', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis({ stats: { listedNotSuspected: 3 } }) })

  expect(screen.getByText(/3 listed roofs were not flagged by the model/)).toBeDefined()
})

it('przyznaje sie, gdy lista dachow z modelu jest przycieta', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis({ truncated: true }) })

  expect(screen.getByText(/The list of roofs is truncated/)).toBeDefined()
})

it('pokazuje blad modelu doslownie i zostawia przycisk do ponowienia', () => {
  const message = 'The model is not responding. Try again in a moment.'
  renderPanel(aSmallScan(), { analysisError: message })

  expect(screen.getByText(message)).toBeDefined()
  expect(analyseButton().disabled).toBe(false)
})

// Nie ma czego analizowac, wiec nie ma tez czym kusic: pusty obszar konczy sie na wyjasnieniu.
it('nie proponuje analizy w obszarze bez budynkow', () => {
  renderPanel(
    aScan({
      stats: someStats({ total: 0, listed: 0, notListed: 0, listedShare: 0, roofAreaM2: 0, listedRoofAreaM2: 0, registryRecords: 0 }),
      listedBuildings: [],
    }),
  )

  expect(screen.queryByText('Analyse roofs with the model')).toBeNull()
})
