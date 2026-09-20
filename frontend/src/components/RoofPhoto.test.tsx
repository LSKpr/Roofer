import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { roofImageUrl } from '../api/client'
import { RoofPhoto } from './RoofPhoto'

function photo() {
  return screen.getByAltText(/dachu budynku/i)
}

it('siega po wycinek ortofoto dokladnie tego budynku, przez funkcje z klienta API', () => {
  render(<RoofPhoto buildingId={7} />)

  const src = photo().getAttribute('src')
  expect(src).toBe(roofImageUrl(7))
  expect(src).toContain('/api/buildings/7/roof.png?size=384')
})

it('przekazuje wskazany rozmiar kadru', () => {
  render(<RoofPhoto buildingId={7} size={256} />)

  expect(photo().getAttribute('src')).toContain('size=256')
})

it('nie blokuje pierwszego renderu: zdjecie wczytuje sie leniwie', () => {
  render(<RoofPhoto buildingId={7} />)

  expect(photo().getAttribute('loading')).toBe('lazy')
  expect(screen.getByTestId('roof-photo').getAttribute('data-state')).toBe('loading')
})

it('podaje atrybucje GUGiK, bo wymaga jej regulamin usługi', () => {
  render(<RoofPhoto buildingId={7} />)

  expect(screen.getByText('Ortofotomapa: GUGiK / Geoportal.gov.pl')).toBeDefined()
})

it('mowi, czego zdjecie nie dowodzi', () => {
  render(<RoofPhoto buildingId={7} />)

  expect(screen.getByText(/w momencie nalotu lotniczego/)).toBeDefined()
  expect(screen.getByText(/Nie potwierdza materiału pokrycia/)).toBeDefined()
})

it('zamienia niedostepne ortofoto na komunikat, nie na pusta ramke', () => {
  render(<RoofPhoto buildingId={7} />)

  fireEvent.error(photo())

  expect(screen.getByText('Ortofotomapa niedostępna')).toBeDefined()
  expect(screen.queryByAltText(/dachu budynku/i)).toBeNull()
  expect(screen.getByTestId('roof-photo').getAttribute('data-state')).toBe('unavailable')
})

it('atrybucja zostaje takze wtedy, gdy zdjecia nie ma', () => {
  render(<RoofPhoto buildingId={7} />)

  fireEvent.error(photo())

  expect(screen.getByText('Ortofotomapa: GUGiK / Geoportal.gov.pl')).toBeDefined()
})

it('po wczytaniu odslania zdjecie', () => {
  render(<RoofPhoto buildingId={7} />)

  fireEvent.load(photo())

  expect(screen.getByTestId('roof-photo').getAttribute('data-state')).toBe('ready')
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const view = render(<RoofPhoto buildingId={7} />)

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/wykryto|brak azbestu|bezpieczny|czysty/i)
})
