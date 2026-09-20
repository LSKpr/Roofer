import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { RegistryToggle } from './RegistryToggle'

const LABEL = 'Podświetl zgłoszone w rejestrze'

it('jest prawdziwym polem wyboru z podpisem, a nie divem udajacym przelacznik', () => {
  render(<RegistryToggle checked onChange={() => {}} />)

  const input = screen.getByLabelText(LABEL) as HTMLInputElement
  expect(input.tagName).toBe('INPUT')
  expect(input.type).toBe('checkbox')
  expect(screen.getByRole('checkbox', { name: LABEL })).toBe(input)
})

/** Etykieta powiazana przez `htmlFor`: klik w tekst ma przelaczac pole, tak jak w formularzu. */
it('przelacza sie klikniesciem w sam tekst etykiety', () => {
  const onChange = vi.fn()
  render(<RegistryToggle checked onChange={onChange} />)

  const input = screen.getByLabelText(LABEL) as HTMLInputElement
  const label = screen.getByText(LABEL) as HTMLLabelElement
  expect(label.htmlFor).toBe(input.id)
  expect(input.id).not.toBe('')

  fireEvent.click(label)
  expect(onChange).toHaveBeenCalledWith(false)
})

it('oddaje rodzicowi nowa wartosc, a nie zdarzenie', () => {
  const onChange = vi.fn()
  const view = render(<RegistryToggle checked onChange={onChange} />)

  fireEvent.click(screen.getByLabelText(LABEL))
  expect(onChange).toHaveBeenCalledWith(false)

  view.rerender(<RegistryToggle checked={false} onChange={onChange} />)
  fireEvent.click(screen.getByLabelText(LABEL))
  expect(onChange).toHaveBeenLastCalledWith(true)
  expect(onChange).toHaveBeenCalledTimes(2)
})

// Komponent jest prezentacyjny: o zaznaczeniu decyduje prop, a nie wlasny stan pola.
it('odwzorowuje props `checked`, zamiast trzymac wlasny stan', () => {
  const view = render(<RegistryToggle checked onChange={() => {}} />)
  expect((screen.getByLabelText(LABEL) as HTMLInputElement).checked).toBe(true)

  view.rerender(<RegistryToggle checked={false} onChange={() => {}} />)
  expect((screen.getByLabelText(LABEL) as HTMLInputElement).checked).toBe(false)

  view.rerender(<RegistryToggle checked onChange={() => {}} />)
  expect((screen.getByLabelText(LABEL) as HTMLInputElement).checked).toBe(true)
})

it('zostawia obsluge klawiatury natywnemu polu', () => {
  render(<RegistryToggle checked onChange={() => {}} />)

  const input = screen.getByLabelText(LABEL)
  expect(input.getAttribute('tabindex')).toBeNull()
  expect(input.getAttribute('role')).toBeNull()
  input.focus()
  expect(document.activeElement).toBe(input)
})

/** Jezyk wizualny raportu: wlosowe linie i promien 2 px, zadnego szkla, pigulek ani gradientow. */
it('wyglada jak rodzenstwo pozostalych paneli nad mapa', () => {
  const { container } = render(<RegistryToggle checked onChange={() => {}} className="mt-1" />)

  const markup = container.innerHTML
  expect(markup).toContain('border-hairline')
  expect(markup).toContain('rounded-card')
  expect(markup).toContain('label-micro')
  expect(markup).not.toContain('backdrop-blur')
  expect(markup).not.toContain('rounded-full')
  expect(markup).not.toContain('gradient')
  // Klasa z propsa ma trafic na sekcje, tak jak w Legend i BasemapSwitcher.
  expect(container.querySelector('section')?.className).toContain('mt-1')
})

// Kolor zaznaczenia bierzemy z tokenu --color-accent przez `accent-accent`; test pilnuje,
// ze nikt nie wstawil tu drugiego, wlasnego hexa.
it('zaznacza sie kolorem akcentu z tokenu, a nie wlasnym hexem', () => {
  render(<RegistryToggle checked onChange={() => {}} />)

  const input = screen.getByLabelText(LABEL)
  expect(input.className).toContain('accent-accent')
  expect(input.getAttribute('style')).toBeNull()
})
