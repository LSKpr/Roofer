import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { BASEMAPS, BASEMAP_IDS } from '../map/basemap'
import { BasemapSwitcher } from './BasemapSwitcher'

it('pokazuje etykiety wszystkich podkladow z definicji stylow', () => {
  render(<BasemapSwitcher value="standard" onChange={() => {}} />)

  expect(screen.getByText('Base map')).toBeDefined()
  for (const id of BASEMAP_IDS) {
    expect(screen.getByRole('button', { name: BASEMAPS[id].label })).toBeDefined()
  }
  expect(screen.getAllByRole('button')).toHaveLength(BASEMAP_IDS.length)
})

/** Kolejnosc jest czescia kontraktu: od najbardziej informacyjnego podkladu do najcichszego. */
it('trzyma kolejnosc przyciskow zgodna z BASEMAP_IDS', () => {
  render(<BasemapSwitcher value="standard" onChange={() => {}} />)

  const labels = screen.getAllByRole('button').map((button) => button.textContent)
  expect(labels).toEqual(BASEMAP_IDS.map((id) => BASEMAPS[id].label))
})

it('wola onChange z identyfikatorem klikanego podkladu', () => {
  const onChange = vi.fn()
  render(<BasemapSwitcher value="standard" onChange={onChange} />)

  fireEvent.click(screen.getByRole('button', { name: BASEMAPS.orthophoto.label }))
  expect(onChange).toHaveBeenCalledWith('orthophoto')

  fireEvent.click(screen.getByRole('button', { name: BASEMAPS.minimal.label }))
  expect(onChange).toHaveBeenCalledWith('minimal')
  expect(onChange).toHaveBeenCalledTimes(2)
})

it('zaznacza tylko aktywny podklad przez aria-pressed', () => {
  render(<BasemapSwitcher value="orthophoto" onChange={() => {}} />)

  for (const id of BASEMAP_IDS) {
    const button = screen.getByRole('button', { name: BASEMAPS[id].label })
    expect(button.getAttribute('aria-pressed')).toBe(id === 'orthophoto' ? 'true' : 'false')
  }
})

it('przenosi zaznaczenie, gdy rodzic zmieni wartosc', () => {
  const view = render(<BasemapSwitcher value="standard" onChange={() => {}} />)
  view.rerender(<BasemapSwitcher value="minimal" onChange={() => {}} />)

  expect(screen.getByRole('button', { name: BASEMAPS.minimal.label }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: BASEMAPS.standard.label }).getAttribute('aria-pressed')).toBe('false')
})

/**
 * Kolejnosc tabulacji i obsluga Entera ma zostac natywna: `<button type="button">` bez wlasnego
 * `tabindex` i bez `role`, ktory odebralby przyciskowi zachowanie z klawiatury.
 */
it('zostawia obsluge klawiatury natywnym przyciskom', () => {
  render(<BasemapSwitcher value="standard" onChange={() => {}} />)

  for (const id of BASEMAP_IDS) {
    const button = screen.getByRole('button', { name: BASEMAPS[id].label })
    expect(button.tagName).toBe('BUTTON')
    expect(button.getAttribute('type')).toBe('button')
    expect(button.getAttribute('tabindex')).toBeNull()
  }

  const first = screen.getByRole('button', { name: BASEMAPS[BASEMAP_IDS[0]].label })
  first.focus()
  expect(document.activeElement).toBe(first)
})

/** Jezyk wizualny raportu: wlosowe linie i promien 2 px, zadnego szkla ani pigulek. */
it('nie uzywa szkla, gradientow ani zaokraglen typu pigulka', () => {
  const { container } = render(<BasemapSwitcher value="standard" onChange={() => {}} />)

  const markup = container.innerHTML
  expect(markup).not.toContain('backdrop-blur')
  expect(markup).not.toContain('rounded-full')
  expect(markup).not.toContain('gradient')
  expect(markup).toContain('border-hairline')
})
