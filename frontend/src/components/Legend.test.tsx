import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { HEATMAP_RAMP_COLORS, POLYGON_MIN_ZOOM, STATUS_COLORS } from '../map/layers'
import { LISTED_COLOR, Legend, NOT_LISTED_COLOR } from './Legend'

/** jsdom zapisuje kolor w stylu po swojemu, wiec porownujemy po tej samej normalizacji. */
function asStyleValue(color: string): string {
  const probe = document.createElement('span')
  probe.style.backgroundColor = color
  return probe.style.backgroundColor
}

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

it('mowi, ze cieplo to zageszczenie zgloszen, a nie ilosc azbestu ani ryzyko', () => {
  render(<Legend />)

  expect(screen.getByText(/zagęszczenie budynków zgłoszonych w rejestrze GeoAzbest/)).toBeDefined()
  expect(screen.getByText(/nie ilość azbestu i nie poziom ryzyka/)).toBeDefined()
})

// Najwazniejsze zdanie legendy: mapa gestosci zgloszen wyglada jak mapa problemu, a gmina,
// ktora nie prowadzi inwentaryzacji, bedzie na niej pusta.
it('tlumaczy, ze pusty obszar znaczy „nikt nic nie zglosil", a nie „nic tam nie ma"', () => {
  render(<Legend />)

  expect(screen.getByText(/wyłącznie zgłoszone budynki/)).toBeDefined()
  expect(screen.getByText(/nikt nic tu nie zgłosił/)).toBeDefined()
  expect(screen.getByText(/nie „nic tam nie ma"/)).toBeDefined()
})

it('uprzedza, od ktorego zoomu sa obrysy i klikalne budynki', () => {
  render(<Legend />)

  expect(screen.getByText(new RegExp(`Obrysy budynków pojawiają się od zoomu ${POLYGON_MIN_ZOOM}`))).toBeDefined()
  expect(POLYGON_MIN_ZOOM).toBe(14)
  expect(screen.getByText(/komórka siatki nie jest budynkiem/)).toBeDefined()
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
  expect(LISTED_COLOR).toBe(STATUS_COLORS.listed)
  expect(NOT_LISTED_COLOR).toBe(STATUS_COLORS.notListed)
})

it('rysuje probki jako kwadraty w kolorze statusu, bez kolorowych plakietek', () => {
  render(<Legend />)

  const [listed, notListed] = screen.getAllByTestId('legend-swatch')
  expect(listed.getAttribute('style')).toContain('background-color')
  expect(listed.className).not.toContain('rounded')
  expect(notListed.className).not.toContain('rounded')
})

// Probka rampy musi byc ta sama rampa co na mapie — inaczej legenda tlumaczy inne kolory,
// niz widac na ekranie.
it('odwzorowuje rampe heatmapy tymi samymi kolorami co warstwa mapy', () => {
  render(<Legend />)

  const steps = screen.getAllByTestId('legend-heat-step')
  expect(steps.map((step) => step.style.backgroundColor)).toEqual(HEATMAP_RAMP_COLORS.map(asStyleValue))
  expect(steps).toHaveLength(HEATMAP_RAMP_COLORS.length)
})

it('podpisuje oba konce paska, zeby nie trzeba bylo zgadywac kierunku', () => {
  render(<Legend />)

  expect(screen.getByText('Pojedyncze zgłoszenia')).toBeDefined()
  expect(screen.getByText('Skupisko')).toBeDefined()
})
