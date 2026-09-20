import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { roofImageUrl } from '../api/client'
import { FlaggedRoofTile, THUMBNAIL_SIZE } from './FlaggedRoofTile'

type Options = {
  id?: number
  probability?: number
  areaM2?: number
  size?: number
  onPick?: (id: number) => void
}

function renderTile(options: Options = {}) {
  return render(
    <FlaggedRoofTile
      id={options.id ?? 200}
      probability={options.probability ?? 0.72}
      areaM2={options.areaM2 ?? 150}
      size={options.size}
      onPick={options.onPick ?? (() => {})}
    />,
  )
}

function tile(): HTMLElement {
  return screen.getByTestId('flagged-roof-tile')
}

function photo(): HTMLElement {
  return screen.getByAltText(/roof of building/i)
}

it('siega po wycinek ortofoto tego dachu, przez funkcje z klienta API', () => {
  renderTile({ id: 201 })

  const src = photo().getAttribute('src')

  expect(src).toBe(roofImageUrl(201, THUMBNAIL_SIZE))
  expect(src).toContain('/api/buildings/201/roof.png?size=128')
})

// 128 to najmniejszy kadr, ktory przyjmuje backend (ROOF_MIN_SIZE), a na kolumne siatki wypada
// tu ~100 px: wiekszy plik nie mialby gdzie sie pokazac, a idzie ich 25 naraz.
it('domyslnie prosi o miniature, nie o kadr dowodowy', () => {
  renderTile()

  expect(THUMBNAIL_SIZE).toBe(128)
  expect(photo().getAttribute('width')).toBe('128')
  expect(photo().getAttribute('height')).toBe('128')
})

it('przekazuje wskazany rozmiar kadru', () => {
  renderTile({ size: 256 })

  expect(photo().getAttribute('src')).toContain('size=256')
})

it('wczytuje kadr leniwie i zaczyna od stanu wczytywania', () => {
  renderTile()

  expect(photo().getAttribute('loading')).toBe('lazy')
  expect(tile().getAttribute('data-state')).toBe('loading')
})

// Bez stalej proporcji siatka przeskakuje w trakcie wczytywania: kadr dochodzi pozniej niz tekst.
it('trzyma kwadratowy kadr, zeby siatka nie skakala przy wczytywaniu', () => {
  renderTile()

  expect(screen.getByTestId('flagged-roof-frame').className).toContain('aspect-square')
})

it('pokazuje ocene w procentach i powierzchnie dachu', () => {
  renderTile({ probability: 0.664, areaM2: 181.5 })

  expect(screen.getByText('66%')).toBeDefined()
  expect(screen.getByText('182 m²')).toBeDefined()
})

it('wyroznia ocene, bo to ona ustawia kolejnosc siatki', () => {
  renderTile({ probability: 0.91 })

  expect(screen.getByText('91%').className).toContain('font-display')
})

it('wola onPick z identyfikatorem tego dachu, gdy klikniety jest caly kafelek', () => {
  const onPick = vi.fn()
  renderTile({ id: 300, onPick })

  fireEvent.click(tile())

  expect(onPick).toHaveBeenCalledTimes(1)
  expect(onPick).toHaveBeenCalledWith(300)
})

// Identyfikator OSM jest adresem tego dachu w reszcie aplikacji, wiec czytnik ekranu musi go
// dostac: raz w podpisie, raz razem z samym kadrem.
it('podaje identyfikator OSM czytnikowi ekranu', () => {
  renderTile({ id: 27469148 })

  expect(screen.getByAltText('Roof of building 27469148')).toBeDefined()
  expect(screen.getByText('OSM 27469148')).toBeDefined()
})

// GUGiK czasem nie oddaje kadru (503 z backendu), a dach bez zdjecia jest nadal dachem
// do sprawdzenia.
it('zamienia niedostepny kadr na komunikat, nie na pusta ramke', () => {
  renderTile({ id: 200, probability: 0.72, areaM2: 150 })

  fireEvent.error(photo())

  expect(screen.getByText('Aerial imagery unavailable')).toBeDefined()
  expect(screen.queryByAltText(/roof of building/i)).toBeNull()
  expect(tile().getAttribute('data-state')).toBe('unavailable')
  expect(screen.getByText('72%')).toBeDefined()
  expect(screen.getByText('150 m²')).toBeDefined()
  expect(screen.getByText('OSM 200')).toBeDefined()
})

it('kafelek bez zdjecia nadal otwiera karte budynku', () => {
  const onPick = vi.fn()
  renderTile({ id: 200, onPick })

  fireEvent.error(photo())
  fireEvent.click(tile())

  expect(onPick).toHaveBeenCalledWith(200)
})

it('po wczytaniu odslania kadr', () => {
  renderTile()

  fireEvent.load(photo())

  expect(tile().getAttribute('data-state')).toBe('ready')
})

// Kropka nosi ten sam token, ktorym mapa maluje obrys tego dachu; zielen jest zakazana, bo
// znaczylaby „czysty dach", a czerwien nalezy do rejestru.
it('znaczy kafelek kolorem podejrzenia, nie czerwienia rejestru', () => {
  renderTile()

  const dot = screen.getByTestId('flagged-roof-dot')

  expect(dot.className).toContain('bg-suspected')
  expect(dot.className).not.toContain('bg-listed')
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const view = renderTile()
  expect(view.container.textContent ?? '').not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)

  fireEvent.error(photo())
  expect(view.container.textContent ?? '').not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)
})
