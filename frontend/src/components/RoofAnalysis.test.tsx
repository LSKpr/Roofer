import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import type { RoofAnalysis as Analysis } from '../api/client'
import { RoofAnalysis } from './RoofAnalysis'

/** `note` przychodzi gotowe z backendu — komponent tylko je pokazuje, wiec atrapa je nasladuje. */
function anAnalysis(overrides: Partial<Analysis> = {}): Analysis {
  return {
    source: 'model',
    verdict: 'suspected',
    probability: 0.72,
    modelName: 'eternit-v1',
    note: 'Scored from a single aerial photo. It does not replace an inspection or a sample test.',
    ...overrides,
  }
}

function renderAnalysis(analysis: Analysis | null) {
  return render(<RoofAnalysis analysis={analysis} loading={false} error={null} />)
}

it('pokazuje werdykt slownie dla podejrzenia, razem ze znacznikiem rejestru', () => {
  renderAnalysis(anAnalysis({ verdict: 'suspected' }))

  expect(screen.getByText('Possible corrugated grey covering (eternit type)')).toBeDefined()
  expect(screen.getByTestId('analysis-dot').className).toContain('bg-listed')
})

it('pokazuje werdykt slownie, gdy model nie widzi takiego pokrycia', () => {
  renderAnalysis(anAnalysis({ verdict: 'unlikely', probability: 0.06 }))

  expect(screen.getByText('The model does not see corrugated grey covering')).toBeDefined()
})

it('pokazuje werdykt slownie, gdy nie wiadomo', () => {
  renderAnalysis(anAnalysis({ verdict: 'unknown', probability: null }))

  expect(screen.getByText('Not known what the covering is')).toBeDefined()
})

it('podaje prawdopodobienstwo jako procent', () => {
  renderAnalysis(anAnalysis({ probability: 0.72 }))

  expect(screen.getByTestId('analysis-probability').textContent).toBe('72%')
  expect(screen.getByText('Probability')).toBeDefined()
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
  expect(screen.getByText(/No numeric result/)).toBeDefined()
  expect(screen.getByText(/not the same as zero/)).toBeDefined()
})

it('ostrzega przy werdykcie, ze wynik demonstracyjny nie pochodzi z modelu', () => {
  renderAnalysis(anAnalysis({ source: 'mock', probability: 0.72 }))

  const warning = screen.getByTestId('analysis-mock-warning')
  expect(warning.textContent).toBe('Demonstration result · no model connected')
  // Ostrzezenie stoi nad werdyktem, a nie drobnym druczkiem na koncu sekcji.
  expect(screen.getByTestId('roof-analysis').firstChild).toBe(warning)
  expect(warning.className).toContain('label-micro')
  expect(screen.getByText(/no model produced it/)).toBeDefined()
})

it('wyszarza sam procent, gdy wynik jest demonstracyjny', () => {
  renderAnalysis(anAnalysis({ source: 'mock', probability: 0.72 }))

  expect(screen.getByTestId('analysis-probability').className).toContain('text-ink-faint')
})

it('nie ostrzega o demonstracji, gdy wynik jest z modelu', () => {
  const view = renderAnalysis(anAnalysis({ source: 'model', probability: 0.72 }))

  expect(screen.queryByTestId('analysis-mock-warning')).toBeNull()
  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/demonstration|illustrative|no model connected/i)
})

it('mowi spokojnie, ze analiza jest niedostepna, bez czerwieni ostrzegawczej', () => {
  const view = renderAnalysis(anAnalysis({ source: 'unavailable', verdict: 'unknown', probability: null }))

  expect(screen.getByTestId('analysis-unavailable-note').textContent).toMatch(/unavailable/i)
  expect(screen.queryByTestId('analysis-mock-warning')).toBeNull()
  const markup = view.container.innerHTML
  expect(markup).not.toContain('text-listed')
  expect(markup).not.toContain('bg-listed')
})

it('pokazuje zastrzezenie z backendu wyciszonym drukiem', () => {
  const note = 'The model scores the look of the covering in the photo, not the material.'
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

  expect(screen.getByText('Loading the covering analysis…')).toBeDefined()
  expect(screen.queryByTestId('roof-analysis')).toBeNull()
})

it('pokazuje komunikat bledu zamiast oceny', () => {
  render(<RoofAnalysis analysis={null} loading={false} error="Backend responded with status 503" />)

  const element = screen.getByTestId('analysis-error')
  expect(element.textContent).toBe('Backend responded with status 503')
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
    // Werdykt mowi o wygladzie pokrycia, nigdy o materiale i nigdy o stanie dachu: ani „wykryto
    // azbest", ani zapewnienie, ze azbestu nie ma albo ze dach jest czysty czy bezpieczny.
    expect(text).not.toMatch(/detected|asbestos-free|no asbestos|safe|clean/i)
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
