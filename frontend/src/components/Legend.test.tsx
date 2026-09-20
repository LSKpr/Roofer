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

  expect(screen.getByText('Listed in the GeoAzbest register')).toBeDefined()
  expect(screen.getByText('Not listed')).toBeDefined()
  expect(screen.getAllByTestId('legend-swatch')).toHaveLength(2)
})

it('mowi wprost, ze brak w rejestrze nie jest dowodem czystego dachu', () => {
  render(<Legend />)

  expect(screen.getByText(/not proof that the roof is clean/)).toBeDefined()
  expect(screen.getByText(/it only means nobody reported it/)).toBeDefined()
})

it('mowi, ze cieplo to zageszczenie zgloszen, a nie ilosc azbestu ani ryzyko', () => {
  render(<Legend />)

  expect(screen.getByText(/density of buildings listed in the GeoAzbest register/)).toBeDefined()
  expect(screen.getByText(/not the amount of asbestos and not a level of risk/)).toBeDefined()
})

// Najwazniejsze zdanie legendy: mapa gestosci zgloszen wyglada jak mapa problemu, a gmina,
// ktora nie prowadzi inwentaryzacji, bedzie na niej pusta.
it('tlumaczy, ze pusty obszar znaczy „nikt nic nie zglosil", a nie „nic tam nie ma"', () => {
  render(<Legend />)

  expect(screen.getByText(/the map shows only listed buildings/)).toBeDefined()
  expect(screen.getByText(/means "nobody reported anything here"/)).toBeDefined()
  expect(screen.getByText(/not "there is nothing there"/)).toBeDefined()
  expect(screen.getByText(/a municipality that runs no inventory stays blank on this map/)).toBeDefined()
})

it('uprzedza, od ktorego zoomu sa obrysy i klikalne budynki', () => {
  render(<Legend />)

  expect(screen.getByText(new RegExp(`Building outlines appear from zoom ${POLYGON_MIN_ZOOM}`))).toBeDefined()
  expect(POLYGON_MIN_ZOOM).toBe(14)
  expect(screen.getByText(/a grid cell is not a building/)).toBeDefined()
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const { container } = render(<Legend />)

  const text = container.textContent ?? ''
  expect(text).not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe/i)
})

// Najwazniejsze zdanie przy wylaczonym przelaczniku: szara mapa wyglada dokladnie tak,
// jakby w tym obszarze nie bylo zadnych zgloszen.
it('mowi wprost, ze podswietlenie rejestru jest wylaczone', () => {
  render(<Legend showRegistry={false} />)

  expect(screen.getByText(/Register highlighting is off/)).toBeDefined()
  expect(screen.getByText(/no red does not mean nobody reported anything/)).toBeDefined()
  // Cieplo znika razem z czerwienia, wiec legenda mowi takze o nim.
  expect(screen.getByText(/The report density shown when zoomed out is hidden too/)).toBeDefined()
})

it('nie straszy tym zdaniem, kiedy podswietlenie dziala', () => {
  render(<Legend />)

  expect(screen.queryByTestId('legend-registry-off')).toBeNull()
  expect(screen.queryByText(/Register highlighting is off/)).toBeNull()
})

// Przelacznik nie moze zabrac legendzie ani jednego ostrzezenia: wylaczone podswietlenie dokłada
// zdanie, a nie zastepuje tego, co legenda mowi o niekompletnym rejestrze.
it('trzyma wszystkie dotychczasowe zdania takze przy wylaczonym podswietleniu', () => {
  const { container } = render(<Legend showRegistry={false} />)

  expect(screen.getByText(/not proof that the roof is clean/)).toBeDefined()
  expect(screen.getByText(/means "nobody reported anything here"/)).toBeDefined()
  expect(screen.getByText(/density of buildings listed in the GeoAzbest register/)).toBeDefined()
  expect(container.textContent ?? '').not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe/i)
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

  expect(screen.getByText('Single reports')).toBeDefined()
  expect(screen.getByText('Cluster')).toBeDefined()
})
