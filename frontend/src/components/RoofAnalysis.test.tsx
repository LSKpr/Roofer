import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import type { RoofAnalysis as Analysis } from '../api/client'
import { RoofAnalysis } from './RoofAnalysis'

function anAnalysis(overrides: Partial<Analysis> = {}): Analysis {
  return {
    source: 'model',
    verdict: 'suspected',
    probability: 0.72,
    modelName: 'eternit-v1',
    note: 'Ocena z jednego zdjęcia lotniczego. Nie zastępuje oględzin ani badania próbki.',
    ...overrides,
  }
}

function renderAnalysis(analysis: Analysis | null) {
  return render(<RoofAnalysis analysis={analysis} loading={false} error={null} />)
}

it('pokazuje werdykt slownie dla podejrzenia, razem ze znacznikiem rejestru', () => {
  renderAnalysis(anAnalysis({ verdict: 'suspected' }))

  expect(screen.getByText('Podejrzenie pokrycia falistego, szarego (typ eternitu)')).toBeDefined()
  expect(screen.getByTestId('analysis-dot').className).toContain('bg-listed')
})

it('pokazuje werdykt slownie, gdy model nie widzi takiego pokrycia', () => {
  renderAnalysis(anAnalysis({ verdict: 'unlikely', probability: 0.06 }))

  expect(screen.getByText('Model nie widzi pokrycia falistego, szarego')).toBeDefined()
})

it('pokazuje werdykt slownie, gdy nie wiadomo', () => {
  renderAnalysis(anAnalysis({ verdict: 'unknown', probability: null }))

  expect(screen.getByText('Nie wiadomo, jakie to pokrycie')).toBeDefined()
})

it('podaje prawdopodobienstwo jako procent', () => {
  renderAnalysis(anAnalysis({ probability: 0.72 }))

  expect(screen.getByTestId('analysis-probability').textContent).toBe('72%')
  expect(screen.getByText('Prawdopodobieństwo')).toBeDefined()
})

it('procent z modelu jest liczba prowadzaca sekcji: szeryfowy i w kolorze tekstu', () => {
  renderAnalysis(anAnalysis({ source: 'model', probability: 0.72 }))

  const probability = screen.getByTestId('analysis-probability').className
  expect(probability).toContain('font-display')
  expect(probability).toContain('text-ink')
  expect(probability).not.toContain('text-ink-faint')
})

it('przy braku wyniku nie pokazuje zadnego procentu, tylko mowi, ze wyniku nie ma', () => {
  const view = renderAnalysis(anAnalysis({ probability: null }))

  expect(screen.queryByTestId('analysis-probability')).toBeNull()
  // Zero znaczyloby „model sprawdzil i nie widzi eternitu", a to inna informacja niz brak wyniku.
  expect(view.container.textContent ?? '').not.toMatch(/\d\s?%/)
  expect(screen.getByText(/Bez wyniku liczbowego/)).toBeDefined()
  expect(screen.getByText(/nie to samo, co zero/)).toBeDefined()
})

it('ostrzega przy werdykcie, ze wynik demonstracyjny nie pochodzi z modelu', () => {
  renderAnalysis(anAnalysis({ source: 'mock', probability: 0.72 }))

  const warning = screen.getByTestId('analysis-mock-warning')
  expect(warning.textContent).toBe('Wynik demonstracyjny · model niepodłączony')
  // Ostrzezenie stoi nad werdyktem, a nie drobnym druczkiem na koncu sekcji.
  expect(screen.getByTestId('roof-analysis').firstChild).toBe(warning)
  expect(warning.className).toContain('label-micro')
  expect(screen.getByText(/nie policzył jej żaden model/)).toBeDefined()
})

it('wyszarza sam procent, gdy wynik jest demonstracyjny', () => {
  renderAnalysis(anAnalysis({ source: 'mock', probability: 0.72 }))

  expect(screen.getByTestId('analysis-probability').className).toContain('text-ink-faint')
})

it('nie ostrzega o demonstracji, gdy wynik jest z modelu', () => {
  const view = renderAnalysis(anAnalysis({ source: 'model', probability: 0.72 }))

  expect(screen.queryByTestId('analysis-mock-warning')).toBeNull()
  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/demonstracyjny|przykładowa|niepodłączony/i)
})

it('mowi spokojnie, ze analiza jest niedostepna, bez czerwieni ostrzegawczej', () => {
  const view = renderAnalysis(anAnalysis({ source: 'unavailable', verdict: 'unknown', probability: null }))

  expect(screen.getByTestId('analysis-unavailable-note').textContent).toMatch(/niedostępna/i)
  expect(screen.queryByTestId('analysis-mock-warning')).toBeNull()
  const markup = view.container.innerHTML
  expect(markup).not.toContain('text-listed')
  expect(markup).not.toContain('bg-listed')
})

it('pokazuje zastrzezenie z backendu wyciszonym drukiem', () => {
  const note = 'Model ocenia wygląd pokrycia ze zdjęcia, nie materiał.'
  renderAnalysis(anAnalysis({ note }))

  const element = screen.getByText(note)
  expect(element.className).toContain('text-xs')
  expect(element.className).toContain('text-ink-faint')
})

it('podpisuje wynik nazwa modelu, gdy backend ja podal', () => {
  renderAnalysis(anAnalysis({ modelName: 'eternit-v1' }))

  expect(screen.getByText('Model: eternit-v1')).toBeDefined()
})

it('nie podpisuje wyniku, gdy nazwy modelu nie ma', () => {
  const view = renderAnalysis(anAnalysis({ modelName: null }))

  expect(view.container.textContent ?? '').not.toMatch(/Model:/)
})

it('informuje o wczytywaniu i nie pokazuje przy tym starej oceny', () => {
  render(<RoofAnalysis analysis={anAnalysis()} loading={true} error={null} />)

  expect(screen.getByText('Wczytuję analizę pokrycia…')).toBeDefined()
  expect(screen.queryByTestId('roof-analysis')).toBeNull()
})

it('pokazuje komunikat bledu zamiast oceny', () => {
  render(<RoofAnalysis analysis={null} loading={false} error="Backend odpowiedział kodem 503" />)

  const element = screen.getByTestId('analysis-error')
  expect(element.textContent).toBe('Backend odpowiedział kodem 503')
  expect(element.className).not.toContain('text-listed')
})

it('nie renderuje nic bez oceny, bledu i wczytywania', () => {
  const view = renderAnalysis(null)

  expect(view.container.firstChild).toBeNull()
})

it('dla braku takiego pokrycia uzywa szarosci, nigdy zieleni', () => {
  const view = renderAnalysis(anAnalysis({ verdict: 'unlikely', probability: 0.04 }))

  expect(screen.getByTestId('analysis-dot').className).toContain('bg-not-listed')
  expect(view.container.innerHTML).not.toMatch(/green|emerald|lime/i)
})

it('dla nieznanego werdyktu tez uzywa szarosci', () => {
  renderAnalysis(anAnalysis({ verdict: 'unknown', probability: null }))

  expect(screen.getByTestId('analysis-dot').className).toContain('bg-not-listed')
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const cases: Analysis[] = [
    anAnalysis({ source: 'model', verdict: 'suspected', probability: 0.72 }),
    anAnalysis({ source: 'mock', verdict: 'unlikely', probability: 0.11 }),
    anAnalysis({ source: 'unavailable', verdict: 'unknown', probability: null }),
  ]

  for (const analysis of cases) {
    const view = renderAnalysis(analysis)
    const text = view.container.textContent ?? ''
    expect(text).not.toMatch(/wykryto azbest|brak azbestu|bezpieczny|czysty dach/i)
    view.unmount()
  }
})

it('nie dodaje wlasnej ramki karty ani naglowka sekcji', () => {
  const view = renderAnalysis(anAnalysis())

  const root = view.container.firstElementChild
  expect(root?.tagName).toBe('DIV')
  expect(root?.className ?? '').not.toContain('rounded-card')
  expect(root?.className ?? '').not.toContain('border-hairline')
  expect(view.container.querySelector('h2, h3')).toBeNull()
})
