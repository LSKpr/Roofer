import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { Village } from '../api/client'
import { VillageJump } from './VillageJump'

const JANIKOW: Village = {
  name: 'Janików',
  folder: 'miasteczko1',
  sw: { lng: 21.5703, lat: 51.5575 },
  ne: { lng: 21.6084, lat: 51.5802 },
  crops: 372,
  buildings: 458,
  gsdM: 0.05,
  frameM: 12.8,
  acquiredFrom: '2023-12-05',
  acquiredTo: '2023-12-12',
}

const BIEGANOW: Village = {
  name: 'Bieganów',
  folder: 'miasteczko2',
  sw: { lng: 20.4712, lat: 52.0369 },
  ne: { lng: 20.5063, lat: 52.0551 },
  crops: 429,
  buildings: 549,
  gsdM: 0.05,
  frameM: 12.8,
  acquiredFrom: '2023-12-12',
  acquiredTo: '2023-12-12',
}

const VILLAGES = [JANIKOW, BIEGANOW]

it('daje po jednym przycisku na wies', () => {
  render(<VillageJump villages={VILLAGES} onPick={() => {}} />)

  expect(screen.getAllByRole('button')).toHaveLength(2)
  expect(screen.getByRole('button', { name: /Janików/ })).toBeDefined()
  expect(screen.getByRole('button', { name: /Bieganów/ })).toBeDefined()
})

// Liczby sa z API, nie z kodu: to one tlumacza, dlaczego akurat te wsie maja wlasny przycisk.
it('pokazuje liczbe wycinkow i rozdzielczosc z API', () => {
  render(<VillageJump villages={[JANIKOW]} onPick={() => {}} />)

  expect(screen.getByText('372 crops · 5 cm/px')).toBeDefined()
})

it('oddaje klikniete wies rodzicowi razem z jej obwiednia', () => {
  const onPick = vi.fn()
  render(<VillageJump villages={VILLAGES} onPick={onPick} />)

  fireEvent.click(screen.getByRole('button', { name: /Bieganów/ }))

  expect(onPick).toHaveBeenCalledTimes(1)
  expect(onPick).toHaveBeenCalledWith(BIEGANOW)
})

// Backend bez skonfigurowanych danych oddaje pusta liste — wtedy nie ma czego pokazac,
// a naglowek bez przyciskow wygladalby na awarie.
it('nie renderuje nic przy pustej liscie', () => {
  const view = render(<VillageJump villages={[]} onPick={() => {}} />)

  expect(view.container.firstChild).toBeNull()
  expect(screen.queryByText('Cached imagery')).toBeNull()
})

it('mowi, ze te wsie maja zdjecia na dysku, a nie ze cos je wyroznia w rejestrze', () => {
  render(<VillageJump villages={VILLAGES} onPick={() => {}} />)

  expect(screen.getByText('Cached imagery')).toBeDefined()
  expect(screen.getByText(/already exported to disk/)).toBeDefined()
  expect(screen.getByText(/without a network request/)).toBeDefined()
  expect(screen.getByText(/Nothing in the register singles them out/)).toBeDefined()
})

// Dwa przyciski obok siebie same z siebie czytaja sie jak lista miejsc wybranych merytorycznie.
// Zadnego takiego slowa nie ma tu prawa byc: wybor zrobil nasz dysk, nie rejestr ani model.
it('nie sugeruje, ze wsie zostaly wybrane z powodow merytorycznych', () => {
  const view = render(<VillageJump villages={VILLAGES} onPick={() => {}} />)

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/detected|flagged|worst|priority|hotspot|most/i)
})

// Backend oddaje `gsdM: null`, gdy kadry jednej wsi maja rozna rozdzielczosc — jedna liczba bylaby
// wtedy polprawda. Mnozenie `null * 100` dalo by „0 cm/px", czyli liczbe wziete z powietrza.
it('pomija rozdzielczosc, gdy backend jej nie podal, zamiast pokazac zero', () => {
  render(<VillageJump villages={[{ ...JANIKOW, gsdM: null }]} onPick={() => {}} />)

  // Sam przycisk, nie podpis sekcji: zdanie o zdjeciach z dysku tez zawiera slowo „crops".
  const button = screen.getByRole('button', { name: /Janików/ })

  expect(button.textContent).toBe('Janików372 crops')
  expect(button.textContent).not.toMatch(/cm\/px/)
  expect(button.textContent).not.toMatch(/\b0\b/)
})

it('przy podanej rozdzielczosci pokazuje ja obok liczby kadrow', () => {
  render(<VillageJump villages={[JANIKOW]} onPick={() => {}} />)

  expect(screen.getByText('372 crops · 5 cm/px')).toBeDefined()
})
