import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { AreaAnalysis, AreaAnalysisStats, AreaScan, AreaStats, ListedBuilding, SuspectedRoof } from '../api/client'
import type { AreaAnalysisProgress } from '../hooks/useAreaAnalysis'
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

/** Skan, ktory miesci sie w budzecie czasu z zapasem: 74 budynki pod Zwoleniem. */
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

type RoofSpec = { count: number; probability: number; listed?: boolean; areaM2?: number; firstId: number }

function someRoofs({ count, probability, listed = false, areaM2 = 100, firstId }: RoofSpec): SuspectedRoof[] {
  return Array.from({ length: count }, (_, index) => ({
    id: firstId + index,
    probability,
    listed,
    areaM2,
    geometry: null,
  }))
}

/**
 * Oceny pojedynczych dachow z tego samego przebiegu. Panel liczy z nich wszystko, co zalezy od
 * progu, wiec przy progu 0,5 musza dawac dokladnie `MODEL_STATS`: 16 z flaga (2 zgloszone,
 * 14 nie), 2 431,5 m² powierzchni z flaga i jeden zgloszony dach ponizej progu.
 */
const MODEL_ROOFS: SuspectedRoof[] = [
  ...someRoofs({ count: 2, probability: 0.81, listed: true, areaM2: 150, firstId: 100 }),
  ...someRoofs({ count: 13, probability: 0.72, areaM2: 150, firstId: 200 }),
  ...someRoofs({ count: 1, probability: 0.66, areaM2: 181.5, firstId: 300 }),
  ...someRoofs({ count: 1, probability: 0.31, listed: true, areaM2: 120, firstId: 400 }),
  ...someRoofs({ count: 47, probability: 0.18, areaM2: 100, firstId: 500 }),
]

type AnalysisOverrides = Omit<Partial<AreaAnalysis>, 'stats'> & { stats?: Partial<AreaAnalysisStats> }

function anAnalysis(overrides: AnalysisOverrides = {}): AreaAnalysis {
  const { stats, ...rest } = overrides
  return { stats: { ...MODEL_STATS, ...stats }, buildings: MODEL_ROOFS, truncated: false, ...rest }
}

type PanelOptions = {
  onClose?: () => void
  onPickBuilding?: (id: number) => void
  loading?: boolean
  error?: string | null
  analysis?: AreaAnalysis | null
  analysisLoading?: boolean
  analysisError?: string | null
  analysisProgress?: AreaAnalysisProgress | null
  analysisSkipped?: boolean
  onAnalyse?: () => void
  threshold?: number | null
  onThresholdChange?: (value: number) => void
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
      analysisProgress={options.analysisProgress ?? null}
      analysisSkipped={options.analysisSkipped ?? false}
      onAnalyse={options.onAnalyse ?? (() => {})}
      threshold={options.threshold ?? null}
      onThresholdChange={options.onThresholdChange ?? (() => {})}
    />,
  )
}

/** Przycisk analizy jest jedynym przyciskiem z ta etykieta, wiec szukamy go po niej. */
function analyseButton(): HTMLButtonElement {
  return screen.getByText('Analyse roofs with the model') as HTMLButtonElement
}

/** Suwak progu szukamy tak, jak znalazlby go czytnik ekranu: po etykiecie. */
function thresholdSlider(): HTMLInputElement {
  return screen.getByLabelText('Suspicion threshold') as HTMLInputElement
}

/** Wartosc wiersza po jego etykiecie: te same male liczby powtarzaja sie w panelu kilka razy. */
function rowValue(label: string): string {
  return screen.getByText(label).nextElementSibling?.textContent ?? ''
}

/** Wiersze listy niezgloszonych dachow z flaga: to przyciski tej sekcji, w kolejnosci z ekranu. */
function flaggedRows(): HTMLElement[] {
  return within(screen.getByTestId('flagged-roofs')).getAllByRole('button')
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

// Limit 500 budynkow przestal byc granica: obszar wiekszy niz jedno zadanie modelu dzieli sie na
// kawalki. 1 338 budynkow (i 4 km²) to dzis zwykly obszar do analizy, a nie odmowa.
it('nie blokuje obszaru, ktory nie miesci sie w jednym zadaniu modelu', () => {
  const onAnalyse = vi.fn()
  renderPanel(aScan({ areaKm2: 6.3 }), { onAnalyse })

  expect(analyseButton().disabled).toBe(false)
  expect(screen.queryByText(/The model accepts up to/)).toBeNull()
  expect(screen.queryByText(/km²; this selection is/)).toBeNull()

  fireEvent.click(analyseButton())
  expect(onAnalyse).toHaveBeenCalledTimes(1)
})

// Liczbe budynkow znamy z wyniku skanu, wiec powod odmowy stoi przy przycisku, zanim uzytkownik
// w niego kliknie. Granica jest jedna i jest nia czas: 2 000 dachow to poltorej do czterech minut,
// a 10 631 budynkow z centrum Warszawy to kwadranse.
it('wylacza przycisk i podaje liczbe dachow, gdy obszar przekracza budzet czasu', () => {
  const onAnalyse = vi.fn()
  const centreOfWarsaw = someStats({ total: 10631, listed: 11, notListed: 10620, listedShare: 0.001 })
  renderPanel(aScan({ stats: centreOfWarsaw, areaKm2: 24.2 }), { onAnalyse })

  expect(analyseButton().disabled).toBe(true)
  expect(screen.getByText('The model can analyse up to 2,000 roofs in one go; this area has 10,631.')).toBeDefined()

  fireEvent.click(analyseButton())
  expect(onAnalyse).not.toHaveBeenCalled()
})

// Granica jest granica, a nie „okolo": 2 000 dachow jeszcze przechodzi, 2 001 juz nie.
it('przepuszcza obszar dokladnie na granicy budzetu', () => {
  renderPanel(aScan({ stats: someStats({ total: 2000, listed: 10, notListed: 1990, listedShare: 0.005 }) }))
  expect(analyseButton().disabled).toBe(false)

  renderPanel(aScan({ stats: someStats({ total: 2001, listed: 10, notListed: 1991, listedShare: 0.005 }) }))
  const buttons = screen.getAllByText('Analyse roofs with the model') as HTMLButtonElement[]
  expect(buttons[1].disabled).toBe(true)
  expect(screen.getByText('The model can analyse up to 2,000 roofs in one go; this area has 2,001.')).toBeDefined()
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

/** Skan obszaru, ktory dzieli sie na kilka kawalkow: 691 budynkow pod Zwoleniem. */
function aStreamedScan(overrides: Partial<AreaScan> = {}): AreaScan {
  return aScan({
    stats: someStats({ total: 691, listed: 12, notListed: 679, listedShare: 0.017 }),
    areaKm2: 0.686,
    ...overrides,
  })
}

// Bez tej linii panel mowilby „Analysing 691 roofs…" przez kilka minut, nie pokazujac, ze czesc
// obszaru jest juz policzona.
it('pokazuje, ktory kawalek idzie teraz i ile dachow juz ocenil', () => {
  renderPanel(aStreamedScan(), {
    analysisLoading: true,
    analysisProgress: { done: 2, total: 7, buildings: 214 },
  })

  expect(screen.getByText('Analysing area 3 of 7 · 214 roofs so far')).toBeDefined()
  // Szacunek czasu zostaje obok postepu: to on mowi, na ile jeszcze usiasc.
  expect(screen.getByText('up to about 2 min')).toBeDefined()
})

// Przed pierwsza ocena nie ma czego liczyc, a „0 roofs so far" nie jest informacja.
it('nie podaje liczby dachow, dopoki zadna ocena nie splynela', () => {
  renderPanel(aStreamedScan(), { analysisLoading: true, analysisProgress: { done: 0, total: 7, buildings: 0 } })

  expect(screen.getByText('Analysing area 1 of 7…')).toBeDefined()
  expect(screen.queryByText(/roofs so far/)).toBeNull()
})

// Caly sens strumieniowania: liczby i lista sa widoczne, zanim skonczy sie caly obszar.
it('pokazuje liczby i liste juz w trakcie pracy', () => {
  renderPanel(aStreamedScan(), {
    analysisLoading: true,
    analysis: anAnalysis(),
    analysisProgress: { done: 3, total: 7, buildings: 214 },
  })

  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('14')
  expect(screen.getByTestId('flagged-roofs')).toBeDefined()
  expect(screen.getByText('Analysing area 4 of 7 · 214 roofs so far')).toBeDefined()
})

// Czesciowe „14" bez tego zdania czyta sie jak wynik koncowy calego zaznaczenia.
it('mowi przy niepelnym wyniku, jakiej czesci obszaru dotycza liczby', () => {
  renderPanel(aStreamedScan(), {
    analysisLoading: true,
    analysis: anAnalysis(),
    analysisProgress: { done: 3, total: 7, buildings: 214 },
  })

  expect(screen.getByText('These numbers cover 3 of 7 areas analysed so far.')).toBeDefined()
})

// Po ostatnim kawalku liczby dotycza calego obszaru, wiec zdanie o czesci musi zniknac — inaczej
// samo podwazaloby kompletny wynik.
it('nie mowi o czesci obszaru, gdy wrocily wszystkie kawalki', () => {
  renderPanel(aStreamedScan(), {
    analysis: anAnalysis(),
    analysisProgress: { done: 7, total: 7, buildings: 640 },
  })

  expect(screen.queryByText(/These numbers cover/)).toBeNull()
  expect(screen.queryByText(/Analysing area/)).toBeNull()
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('14')
})

// Blad kawalka nie wyrzuca dotychczasowej pracy: liczby zostaja, komunikat stoi nad nimi,
// a zdanie o czesci obszaru tlumaczy, ile z niego zdazylo sie policzyc.
it('zostawia niepelny wynik z komunikatem bledu i zdaniem o czesci obszaru', () => {
  renderPanel(aStreamedScan(), {
    analysis: anAnalysis(),
    analysisError: 'The model is not responding.',
    analysisProgress: { done: 2, total: 7, buildings: 180 },
  })

  expect(screen.getByText('The model is not responding.')).toBeDefined()
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('14')
  expect(screen.getByText('These numbers cover 2 of 7 areas analysed so far.')).toBeDefined()
  // Przycisk nie wraca, dopoki na ekranie stoi wynik — inaczej klik zaczynalby caly obszar od zera.
  expect(screen.queryByText('Analyse roofs with the model')).toBeNull()
})

// Fragment bez swojego kawalka nie zostal obejrzany wcale — brak pomaranczowych obrysow w tym
// miejscu wygladalby jak wynik modelu.
it('mowi wprost, ze czesc zaznaczenia byla za gesta i zostala pominieta', () => {
  renderPanel(aStreamedScan(), { analysis: anAnalysis(), analysisSkipped: true })

  expect(screen.getByText(/Part of this selection is too dense to split into areas the model accepts/)).toBeDefined()
  expect(screen.getByText(/the model never looked at those roofs, and no orange there is not a result/)).toBeDefined()
})

it('nie wspomina o pominietej czesci, gdy plan objal cale zaznaczenie', () => {
  renderPanel(aStreamedScan(), { analysis: anAnalysis(), analysisProgress: { done: 7, total: 7, buildings: 640 } })

  expect(screen.queryByText(/too dense/)).toBeNull()
})

// Ten sam straznik slownictwa, co wyzej, ale na stanie czesciowym: to on pokazuje liczby, ktore
// jeszcze nie opisuja calego obszaru, wiec najlatwiej zsunalby sie w „tu azbestu nie ma".
it('nie uzywa slownictwa sugerujacego pomiar azbestu przy niepelnym wyniku', () => {
  const view = renderPanel(aStreamedScan(), {
    analysisLoading: true,
    analysis: anAnalysis(),
    analysisProgress: { done: 3, total: 7, buildings: 214 },
    analysisSkipped: true,
  })

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)
  // Straznik nie moze przechodzic na pustym panelu: zdanie o czesci obszaru musi tam byc.
  expect(text).toMatch(/These numbers cover 3 of 7 areas analysed so far/)
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
  // Liczba bierze sie z ocen, nie ze statystyk backendu, wiec trzy zgloszone dachy ponizej progu.
  const threeListedBelow = anAnalysis({
    buildings: [
      ...someRoofs({ count: 3, probability: 0.2, listed: true, areaM2: 130, firstId: 700 }),
      ...someRoofs({ count: 1, probability: 0.9, areaM2: 140, firstId: 800 }),
    ],
  })

  renderPanel(aSmallScan(), { analysis: threeListedBelow })

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

// Suwak opisuje wynik, wiec bez wyniku nie ma czego nim ustawiac.
it('daje suwak progu dopiero razem z wynikiem modelu', () => {
  renderPanel(aSmallScan())
  expect(screen.queryByLabelText('Suspicion threshold')).toBeNull()

  renderPanel(aSmallScan(), { analysisLoading: true })
  expect(screen.queryByLabelText('Suspicion threshold')).toBeNull()

  renderPanel(aSmallScan(), { analysis: anAnalysis() })
  expect(thresholdSlider()).toBeDefined()
})

it('stawia suwak na progu z odpowiedzi, dopoki nikt go nie ruszyl', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: null })

  expect(thresholdSlider().value).toBe('0.5')
  expect(screen.getByTestId('threshold-value').textContent).toBe('50%')
  expect(screen.queryByText(/Model default/)).toBeNull()
})

it('oddaje nowy prog rodzicowi, bo stan progu trzyma App', () => {
  const onThresholdChange = vi.fn()
  renderPanel(aSmallScan(), { analysis: anAnalysis(), onThresholdChange })

  fireEvent.change(thresholdSlider(), { target: { value: '0.7' } })

  expect(onThresholdChange).toHaveBeenCalledWith(0.7)
})

// Liczby przy podniesionym progu sa policzone z ocen pojedynczych dachow, a nie wziete
// z backendu: model nie jest pytany drugi raz, bo przyjmuje 10 zapytan na minute.
it('przelicza liczby, gdy prog idzie w gore', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.7 })

  // Powyzej 0,7 zostaja dwa zgloszone dachy (0,81) i trzynascie niezgloszonych (0,72).
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('13')
  expect(screen.getByText('15 (23%)')).toBeDefined()
  expect(screen.getByText('2,250 m²')).toBeDefined()
  expect(screen.getByTestId('threshold-value').textContent).toBe('70%')
})

it('przelicza liczby takze wtedy, gdy prog idzie w dol', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.3 })

  // Prog 0,3 doklada zgloszony dach z ocena 0,31, wiec zgloszonych bez flagi nie zostaje ani jeden.
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('14')
  expect(screen.getByText('17 (27%)')).toBeDefined()
  expect(screen.getByText('2,552 m²')).toBeDefined()
  expect(rowValue('Flagged and already listed')).toBe('3')
  expect(rowValue('Listed but not flagged')).toBe('0')
  expect(screen.queryByText(/listed roof was not flagged/)).toBeNull()
})

// Liczba ocenionych i brak oceny nie zaleza od progu: prog przesuwa granice flagi, a nie to,
// ile zdjec model obejrzal.
it('nie rusza liczby ocenionych ani braku ocen, gdy prog sie zmienia', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.95 })

  expect(screen.getByText('Roofs analysed')).toBeDefined()
  expect(screen.getByText('64')).toBeDefined()
  expect(screen.getByText(/10 roofs got no score/)).toBeDefined()
  expect(screen.getByText('70b702')).toBeDefined()
})

// Uzytkownik musi wiedziec, ze patrzy na wlasne ustawienie, a nie na wynik modelu.
it('podaje prog modelu, gdy suwak stoi gdzie indziej', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.35 })

  expect(screen.getByText('Model default: 50%')).toBeDefined()
})

// Prog jest decyzja patrzacego: przesuniecie suwaka zmienia kompromis, nie jakosc modelu.
it('mowi, ze prog jest decyzja uzytkownika, a skutecznosc zmierzono przy domyslnym', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(
    screen.getByText(
      'The threshold is your decision, not a property of the model: both figures above were measured at the model default, and moving the slider trades false alarms against missed roofs rather than changing how well the model sees.',
    ),
  ).toBeDefined()
})

// Najgrozniejszy mozliwy odczyt suwaka: „powyzej jest azbest, ponizej go nie ma".
it('mowi, ze ocena ponizej progu nie jest werdyktem o dachu', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByText(/A roof below the threshold is not cleared/)).toBeDefined()
  expect(screen.getByText(/the model sees less resemblance to corrugated grey sheeting/)).toBeDefined()
  expect(screen.getByText(/never that the roof is without asbestos/)).toBeDefined()
})

// Ten sam straznik slownictwa, co wyzej, ale na stanie z przesunietym suwakiem: to on najlatwiej
// zsunalby sie z „model cos widzi na zdjeciu" na „wykryto azbest".
it('nie uzywa slownictwa sugerujacego pomiar azbestu przy przesunietym suwaku', () => {
  const low = renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0 })
  expect(low.container.textContent ?? '').not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)

  const high = renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 1 })
  expect(high.container.textContent ?? '').not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)
})

// Przy przycietej liscie nie ma z czego przeliczyc calosci, wiec suwak znika, a liczby zostaja
// te z backendu — patrz komentarz w lib/modelStats.ts.
it('przy przycietej liscie nie daje suwaka i mowi, dlaczego', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis({ truncated: true }), threshold: 0.9 })

  expect(screen.queryByLabelText('Suspicion threshold')).toBeNull()
  expect(screen.getByText(/The threshold cannot be moved here/)).toBeDefined()
  // Liczby zostaja policzone przez backend przy jego progu, a nie przy 0,9.
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('14')
  expect(screen.getByText('16 (25%)')).toBeDefined()
})

/** Liczby z koszykow rozkladu ocen: jedna komorka na kazdy przedzial, takze na pusty. */
function bucketCounts(): number[] {
  return screen.getAllByTestId('score-bucket').map((cell) => Number(cell.dataset.count))
}

/**
 * Slupki, ktore prog przemalowal na kolor podejrzenia. Pytamy w obrebie jednego wyniku `render`,
 * bo ten test rysuje panel dwa razy — przy dwoch progach — i oba zostaja w dokumencie.
 */
function suspectedBarsIn(container: HTMLElement): HTMLElement[] {
  const bars = Array.from(container.querySelectorAll<HTMLElement>('[data-testid="score-bar"]'))
  return bars.filter((bar) => bar.className.includes('bg-suspected'))
}

// Suwak bez rozkladu jest galka bez kontekstu: „50%" nie mowi, czy odcina dwa dachy, czy dwiescie.
// Suma slupkow musi byc liczba ocenionych dachow, inaczej wykres opisuje inny obszar niz tabelka.
it('pokazuje rozklad ocen pod suwakiem i sumuje slupki do liczby ocenionych dachow', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByTestId('score-histogram')).toBeDefined()
  expect(bucketCounts().reduce((sum, count) => sum + count, 0)).toBe(MODEL_STATS.analysed)
  // Najwyzszy koszyk to czterdziesci siedem dachow z ocena 0,18 — os pionowa ma jednostke.
  expect(screen.getByText('Tallest bar 47 roofs')).toBeDefined()
})

// Sedno tego wykresu: przy ruchu suwaka widac, co prog zabiera i co dodaje.
it('przemalowuje slupki rozkladu, gdy prog sie zmienia', () => {
  // Ponad 0,5 stoja koszyki z ocenami 0,66, 0,72 i 0,81; ponizej te z 0,18 i 0,31.
  const atDefault = renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.5 })
  expect(suspectedBarsIn(atDefault.container)).toHaveLength(3)

  // Prog 0,7 zabiera koszyk 0,65-0,70, w ktorym siedzi ocena 0,66.
  const higher = renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.7 })
  expect(suspectedBarsIn(higher.container)).toHaveLength(2)

  // Liczba slupkow sie nie zmienia — zmienia sie tylko to, ktore sa pomaranczowe.
  expect(higher.container.querySelectorAll('[data-testid="score-bar"]')).toHaveLength(5)
})

// Dachy bez oceny nie sa na tym wykresie zerem, nie ma ich wcale — bez tego zdania rozklad
// czytaloby sie jako rozklad calego obszaru.
it('mowi pod rozkladem, ze widac w nim tylko dachy ocenione', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByText(/Scored roofs only/)).toBeDefined()
  expect(screen.getByText(/no score is not the same as a score of zero/)).toBeDefined()
})

// Wynik bez ani jednej oceny to nie rozklad rowny zeru, wiec pustej ramki nie rysujemy.
it('nie rysuje rozkladu, gdy zaden dach nie dostal oceny', () => {
  const nothingScored = anAnalysis({
    stats: { analysed: 0, noResult: 12, suspected: 0, suspectedShare: 0, suspectedNotListed: 0, suspectedListed: 0, listedNotSuspected: 0, suspectedRoofAreaM2: 0 },
    buildings: [],
  })

  renderPanel(aSmallScan(), { analysis: nothingScored })

  expect(screen.queryByTestId('score-histogram')).toBeNull()
  expect(screen.queryByText(/Scored roofs only/)).toBeNull()
  // Sam suwak zostaje: prog jest nadal decyzja patrzacego, tylko nie ma czego nim ciac.
  expect(thresholdSlider()).toBeDefined()
})

// Wykres jest ilustracja: kontrolka progu zostaje jedna i ma etykiete dla czytnika ekranu.
it('nie dodaje razem z rozkladem drugiej kontrolki progu', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getAllByRole('slider')).toHaveLength(1)
  expect(thresholdSlider().type).toBe('range')
  expect(screen.getByTestId('score-histogram').getAttribute('aria-hidden')).toBe('true')
})

// Piecset dachow idzie ponad minute. Bez tej informacji panel wyglada na zawieszony, a uzytkownik
// przerywa i probuje jeszcze raz — czyli placi za to samo dwa razy.
it('szacuje czas oczekiwania z liczby dachow', () => {
  renderPanel(aSmallScan(), { analysisLoading: true })
  expect(screen.getByText('usually a few seconds')).toBeDefined()

  const threeHundred = aSmallScan({ stats: someStats({ total: 300, listed: 10, notListed: 290, listedShare: 0.03 }) })
  renderPanel(threeHundred, { analysisLoading: true })
  expect(screen.getByText('up to about 50 seconds')).toBeDefined()
})

// Piecset dachow to gorna granica bramki, wiec to jest najdluzsze oczekiwanie, jakie panel obiecuje.
it('przy limicie bramki obiecuje minuty, a nie sekundy', () => {
  const atLimit = aSmallScan({ stats: someStats({ total: 500, listed: 10, notListed: 490, listedShare: 0.02 }) })

  renderPanel(atLimit, { analysisLoading: true })

  expect(screen.getByText('up to about 2 min')).toBeDefined()
})

it('przy duzym obszarze podaje szacunek w minutach, nie w setkach sekund', () => {
  const thousand = aSmallScan({ stats: someStats({ total: 1000, listed: 20, notListed: 980, listedShare: 0.02 }) })

  renderPanel(thousand, { analysisLoading: true })

  expect(screen.getByText('up to about 3 min')).toBeDefined()
})

// Wlasciwy produkt tej aplikacji: liczba „14" mowi o skali, a te wiersze da sie objechac.
it('wypisuje niezgloszone dachy z flaga: ocena, powierzchnia i identyfikator OSM', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  // Pierwszy wiersz to jeden z trzynastu dachow z ocena 0,72 i powierzchnia 150 m².
  expect(flaggedRows()[0].textContent).toBe('72%150 m²OSM 200')
  // Ostatni to ten z ocena 0,66 — najnizsza nad progiem.
  expect(flaggedRows()[13].textContent).toBe('66%182 m²OSM 300')
})

// Zgloszony dach na tej liscie zamienilby ja w donos na kogos, kto wlasnie zglosil swoj azbest.
it('nie wpuszcza na liste ani zgloszonego dachu, ani oceny ponizej progu', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  const section = screen.getByTestId('flagged-roofs')

  expect(flaggedRows()).toHaveLength(14)
  // 100 i 101 maja najwyzsza ocene (0,81), ale sa w rejestrze.
  expect(within(section).queryByText('OSM 100')).toBeNull()
  expect(within(section).queryByText('OSM 101')).toBeNull()
  expect(within(section).queryByText('81%')).toBeNull()
  // 500 jest poza rejestrem, ale z ocena 0,18 nie jest podejrzeniem.
  expect(within(section).queryByText('OSM 500')).toBeNull()
})

// Naglowek listy i liczba prowadzaca licza to samo z tego samego progu — inaczej panel obiecywalby
// inna liczbe dachow, niz da sie policzyc wierszami.
it('liczba w naglowku listy zgadza sie z liczba prowadzaca', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('14')
  expect(screen.getByText('Not in the register, flagged by the model (14)')).toBeDefined()
})

it('sortuje liste malejaco po ocenie, bo gora listy to pierwszy wyjazd', () => {
  const mixed = anAnalysis({
    buildings: [
      ...someRoofs({ count: 1, probability: 0.55, areaM2: 110, firstId: 900 }),
      ...someRoofs({ count: 1, probability: 0.91, areaM2: 120, firstId: 901 }),
      ...someRoofs({ count: 1, probability: 0.7, areaM2: 130, firstId: 902 }),
    ],
  })

  renderPanel(aSmallScan(), { analysis: mixed })

  expect(flaggedRows().map((row) => row.textContent)).toEqual([
    '91%120 m²OSM 901',
    '70%130 m²OSM 902',
    '55%110 m²OSM 900',
  ])
})

// Wiersz jest droga do karty budynku: tam jest wycinek ortofoto i pelna nota modelu.
it('otwiera karte budynku identyfikatorem z klikniętego wiersza', () => {
  const onPickBuilding = vi.fn()
  renderPanel(aSmallScan(), { analysis: anAnalysis(), onPickBuilding })

  fireEvent.click(within(screen.getByTestId('flagged-roofs')).getByText('OSM 300'))

  expect(onPickBuilding).toHaveBeenCalledTimes(1)
  expect(onPickBuilding).toHaveBeenCalledWith(300)
})

// Suwak dziala na liste natychmiast i bez zapytania do modelu: wybor idzie z ocen, ktore panel
// juz ma w rece.
it('skraca liste, gdy prog idzie w gore', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.7 })

  expect(flaggedRows()).toHaveLength(13)
  expect(screen.getByText('Not in the register, flagged by the model (13)')).toBeDefined()
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('13')
  // Dach z ocena 0,66 wypadl razem z podniesieniem progu.
  expect(within(screen.getByTestId('flagged-roofs')).queryByText('OSM 300')).toBeNull()
})

it('wydluza liste, gdy prog idzie w dol, i przycina ja do dwudziestu pieciu wierszy', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.15 })

  // Prog 0,15 doklada czterdziesci siedem dachow z ocena 0,18: 61 niezgloszonych z flaga.
  expect(screen.getByTestId('suspected-not-listed').textContent).toBe('61')
  expect(screen.getByText('Not in the register, flagged by the model (61)')).toBeDefined()
  expect(flaggedRows()).toHaveLength(25)
  expect(screen.getByText(/showing 25 of 61 roofs/)).toBeDefined()
  expect(screen.getByText(/the numbers above cover the whole area/)).toBeDefined()
})

// Pusta lista to stan progu, nie werdykt o obszarze — wiec mowi zdanie, a nie zostawia pustke.
it('przy progu nad wszystkimi ocenami mowi zdanie zamiast pustej listy', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 1 })

  expect(screen.getByText('Not in the register, flagged by the model (0)')).toBeDefined()
  expect(screen.getByText(/No roof here is both above the threshold and missing from the register/)).toBeDefined()
  expect(within(screen.getByTestId('flagged-roofs')).queryAllByRole('button')).toHaveLength(0)
})

// Lista opisuje wynik modelu, wiec bez wyniku nie ma jej o czym wypisywac.
it('daje liste niezgloszonych dachow dopiero razem z wynikiem modelu', () => {
  renderPanel(aSmallScan())
  renderPanel(aSmallScan(), { analysisLoading: true })
  expect(screen.queryAllByTestId('flagged-roofs')).toHaveLength(0)

  renderPanel(aSmallScan(), { analysis: anAnalysis() })
  expect(screen.queryAllByTestId('flagged-roofs')).toHaveLength(1)
})

// Ta lista najlatwiej w calej aplikacji zsuwa sie z „model cos widzi na zdjeciu" na „wykryto
// azbest", wiec straznik slownictwa stoi tez na samej sekcji.
it('nie uzywa slownictwa sugerujacego pomiar azbestu w liscie niezgloszonych dachow', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis(), threshold: 0.15 })

  const section = screen.getByTestId('flagged-roofs').textContent ?? ''

  expect(section).not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)
  // Sekcja nie moze byc pusta, bo wtedy straznik przechodzilby na niczym.
  expect(section).toMatch(/Roofs to check on site, sorted by score/)
})

it('mowi przy liscie, skad bierze sie ocena i czego brak w rejestrze nie znaczy', () => {
  renderPanel(aSmallScan(), { analysis: anAnalysis() })

  const section = within(screen.getByTestId('flagged-roofs'))

  expect(section.getByText(/only compares how the covering looks on a satellite photo/)).toBeDefined()
  expect(section.getByText(/some of these roofs will not have asbestos cement on them/)).toBeDefined()
  expect(section.getByText(/Missing from the register means nobody reported this building/)).toBeDefined()
  expect(section.getByText(/not that anything is unlawful/)).toBeDefined()
  expect(section.getByText('This is a list to check on site, not a list of findings.')).toBeDefined()
})

/*
 * Powierzchnia zaznaczenia. Stala jedna cyfra po kropce pokazywala maly prostokat jako „0.0 km²",
 * czyli jako zero — a backend liczy te powierzchnie poprawnie (nasz wzor na kuli rozni sie od
 * ST_Area(geography) o stale 0,37%, czyli o roznice kuli i elipsoidy WGS84). Blad byl wylacznie
 * w zapisie liczby, wiec te testy pilnuja zapisu.
 */
it('podaje mala powierzchnie zaznaczenia w metrach, a nie jako zero kilometrow', () => {
  // Kwadrat okolo 200 × 200 m pod Zwoleniem: 0,0404 km², czyli czterdziesci tysiecy metrow.
  renderPanel(aSmallScan({ areaKm2: 0.0404 }))

  expect(screen.getByText('40,400 m²')).toBeDefined()
  expect(screen.queryByText('0.0 km²')).toBeNull()
})

it('powyzej granicy podaje kilometry z jedna cyfra', () => {
  renderPanel(aSmallScan({ areaKm2: 0.686 }))
  expect(screen.getByText('0.7 km²')).toBeDefined()

  renderPanel(aSmallScan({ areaKm2: 24.861 }))
  expect(screen.getByText('24.9 km²')).toBeDefined()
})

// Granica jest granica: 0,1 km² to juz kilometry, ani grosza nizej.
it('przelacza jednostke dokladnie na granicy dziesiatej czesci kilometra', () => {
  renderPanel(aSmallScan({ areaKm2: 0.1 }))
  expect(screen.getByText('0.1 km²')).toBeDefined()

  renderPanel(aSmallScan({ areaKm2: 0.0999 }))
  expect(screen.getByText('99,900 m²')).toBeDefined()
})

// Obszar bez budynkow ma swoj wlasny panel, a w nim ten sam wiersz — i ten sam blad by w nim byl.
it('podaje powierzchnie w metrach takze w obszarze bez budynkow', () => {
  const empty = aSmallScan({
    stats: someStats({ total: 0, listed: 0, notListed: 0, listedShare: 0, roofAreaM2: 0, listedRoofAreaM2: 0, registryRecords: 0 }),
    areaKm2: 0.0404,
    listedBuildings: [],
  })

  renderPanel(empty)

  expect(screen.getByText('There are no OpenStreetMap buildings in this area.')).toBeDefined()
  expect(screen.getByText('40,400 m²')).toBeDefined()
})
