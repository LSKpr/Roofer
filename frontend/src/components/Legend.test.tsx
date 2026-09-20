import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { LISTED_COLOR, Legend, NOT_LISTED_COLOR } from './Legend'

it('opisuje oba statusy, ktore mapa potrafi pokazac', () => {
  render(<Legend />)

  expect(screen.getByText('Zgłoszony w rejestrze GeoAzbest')).toBeDefined()
  expect(screen.getByText('Niezgłoszony')).toBeDefined()
  expect(screen.getAllByTestId('legend-swatch')).toHaveLength(2)
})

it('mowi wprost, ze brak w rejestrze nie jest dowodem czystego dachu', () => {
  render(<Legend />)

  expect(screen.getByText(/nie jest dowodem, że dach jest czysty/)).toBeDefined()
  expect(screen.getByText(/nikt go nie zgłosił/)).toBeDefined()
})

it('uprzedza, ze po oddaleniu widac tylko zgloszone budynki i tylko jako punkty', () => {
  render(<Legend />)

  expect(screen.getByText(/tylko zgłoszone budynki, i to jako punkty/)).toBeDefined()
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const { container } = render(<Legend />)

  const text = container.textContent ?? ''
  expect(text).not.toMatch(/wykryto|brak azbestu|bezpieczny/i)
})

/** Te same wartosci co tokeny --color-listed i --color-not-listed w index.css. */
it('trzyma kolory probek w stalych, zeby zgadzaly sie z warstwami mapy', () => {
  expect(LISTED_COLOR).toBe('#c8102e')
  expect(NOT_LISTED_COLOR).toBe('#9aa5ad')
})

it('rysuje probki jako kwadraty w kolorze statusu, bez kolorowych plakietek', () => {
  render(<Legend />)

  const [listed, notListed] = screen.getAllByTestId('legend-swatch')
  expect(listed.getAttribute('style')).toContain('background-color')
  expect(listed.className).not.toContain('rounded')
  expect(notListed.className).not.toContain('rounded')
})
