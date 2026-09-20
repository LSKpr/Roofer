import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { SuspectedRoof } from '../api/client'
import { FlaggedRoofs } from './FlaggedRoofs'

function aRoof(id: number, probability: number, areaM2 = 150): SuspectedRoof {
  return { id, probability, listed: false, areaM2, geometry: null }
}

/** Trzy dachy z prawdziwego przebiegu, juz posortowane — tak, jak komponent je dostaje. */
const ROOFS: SuspectedRoof[] = [aRoof(200, 0.91, 163), aRoof(201, 0.72, 150), aRoof(202, 0.66, 181.5)]

type Options = {
  roofs?: SuspectedRoof[]
  total?: number
  onPick?: (id: number) => void
  limit?: number
}

function renderList(options: Options = {}) {
  const roofs = options.roofs ?? ROOFS
  return render(
    <FlaggedRoofs
      roofs={roofs}
      total={options.total ?? roofs.length}
      onPick={options.onPick ?? (() => {})}
      limit={options.limit}
    />,
  )
}

/** Wiersze szukamy tak, jak znalazlby je uzytkownik klawiatury: to przyciski w tej sekcji. */
function rows(): HTMLElement[] {
  return within(screen.getByTestId('flagged-roofs')).getAllByRole('button')
}

it('w wierszu podaje ocene, powierzchnie dachu i identyfikator OSM', () => {
  renderList({ roofs: [aRoof(200, 0.91, 163)] })

  expect(screen.getByText('91%')).toBeDefined()
  expect(screen.getByText('163 m²')).toBeDefined()
  expect(screen.getByText('OSM 200')).toBeDefined()
})

// Ocena jest kluczem sortowania, wiec musi byc czytelna bez szukania: szeryfowa, jak liczby
// prowadzace w calym panelu.
it('wyroznia ocene, bo to ona ustawia kolejnosc listy', () => {
  renderList({ roofs: [aRoof(200, 0.91, 163)] })

  expect(screen.getByText('91%').className).toContain('font-display')
})

// Sortuje `selectFlaggedNotListed`, nie komponent: gdyby sortowal oba, kolejnosc na ekranie
// zalezalaby od tego, ktory z nich ostatnio zmieniono.
it('pokazuje wiersze w kolejnosci, w ktorej je dostal', () => {
  renderList({ roofs: [aRoof(300, 0.55), aRoof(301, 0.91), aRoof(302, 0.7)] })

  expect(rows().map((row) => row.textContent)).toEqual([
    '55%150 m²OSM 300',
    '91%150 m²OSM 301',
    '70%150 m²OSM 302',
  ])
})

it('wola onPick z identyfikatorem klikniętego dachu', () => {
  const onPick = vi.fn()
  renderList({ onPick })

  fireEvent.click(screen.getByText('OSM 202'))

  expect(onPick).toHaveBeenCalledTimes(1)
  expect(onPick).toHaveBeenCalledWith(202)
})

it('klikalny jest caly wiersz, a nie tekst w nim', () => {
  renderList()

  expect(rows()).toHaveLength(3)
  for (const row of rows()) expect(row.getAttribute('type')).toBe('button')
})

// Liczba w naglowku ma opisywac caly obszar, bo to ona jest liczba prowadzaca sekcji modelu.
it('w naglowku liczy caly obszar, a nie widoczne wiersze', () => {
  renderList({ total: 120, limit: 2 })

  expect(screen.getByText('Not in the register, flagged by the model (120)')).toBeDefined()
  expect(rows()).toHaveLength(2)
})

it('przycina liste do limitu i mowi, ile z ilu pokazuje', () => {
  const many = Array.from({ length: 30 }, (_, index) => aRoof(400 + index, 0.8))

  renderList({ roofs: many, limit: 25 })

  expect(rows()).toHaveLength(25)
  expect(screen.getByText(/showing 25 of 30 roofs/)).toBeDefined()
  expect(screen.getByText(/the numbers above cover the whole area/)).toBeDefined()
})

it('bez podanego limitu pokazuje najwyzej dwadziescia piec wierszy', () => {
  const many = Array.from({ length: 26 }, (_, index) => aRoof(500 + index, 0.8))

  renderList({ roofs: many })

  expect(rows()).toHaveLength(25)
  expect(screen.getByText(/showing 25 of 26 roofs/)).toBeDefined()
})

it('nie wspomina o przycieciu, gdy widac cala liste', () => {
  renderList()

  expect(screen.queryByText(/truncated/)).toBeNull()
})

// Drugie zrodlo przyciecia: odpowiedz modelu bez wszystkich ocen. Liczba w naglowku jest wtedy
// backendowa i lista musi przyznac, ze opisuje mniej dachow.
it('mowi o przycieciu takze wtedy, gdy krotsza jest sama odpowiedz modelu', () => {
  renderList({ roofs: ROOFS, total: 120 })

  expect(rows()).toHaveLength(3)
  expect(screen.getByText(/showing 3 of 120 roofs/)).toBeDefined()
})

// Pustka wygladalaby jak „nic tu nie ma", a to jest tylko stan progu.
it('pusta liste tlumaczy zdaniem, a nie pustym miejscem', () => {
  renderList({ roofs: [], total: 0 })

  expect(screen.getByText(/No roof here is both above the threshold and missing from the register/)).toBeDefined()
  expect(screen.getByText(/Lower the threshold to see roofs the model scored lower/)).toBeDefined()
  expect(within(screen.getByTestId('flagged-roofs')).queryAllByRole('button')).toHaveLength(0)
})

// Bez tych zdan lista jest donosem: ocena ze zdjecia wygladalaby na ustalenie, a brak wpisu
// w rejestrze na zarzut.
it('mowi, skad bierze sie ocena i ze przy tym progu czesc dachow nie ma eternitu', () => {
  renderList()

  expect(screen.getByText(/Roofs to check on site, sorted by score/)).toBeDefined()
  expect(screen.getByText(/only compares how the covering looks on a satellite photo/)).toBeDefined()
  expect(screen.getByText(/77% accuracy and 63% asbestos recall/)).toBeDefined()
  expect(screen.getByText(/some of these roofs will not have asbestos cement on them/)).toBeDefined()
})

it('mowi, ze brak w rejestrze znaczy tylko tyle, ze nikt nie zglosil', () => {
  renderList()

  expect(screen.getByText(/Missing from the register means nobody reported this building/)).toBeDefined()
  expect(screen.getByText(/not that anything is unlawful/)).toBeDefined()
  expect(screen.getByText(/not that the owner failed to report it/)).toBeDefined()
  expect(screen.getByText(/The register is incomplete/)).toBeDefined()
  expect(screen.getByText(/may have covered something other than the roof/)).toBeDefined()
})

it('mowi wprost, ze to lista do sprawdzenia w terenie, a nie lista ustalen', () => {
  renderList()

  expect(screen.getByText('This is a list to check on site, not a list of findings.')).toBeDefined()
})

// Te zdania dotycza calej sekcji, wiec nie wolno im zniknac razem z wierszami.
it('zostawia zastrzezenia takze przy pustej liscie', () => {
  renderList({ roofs: [], total: 0 })

  expect(screen.getByText(/Roofs to check on site, sorted by score/)).toBeDefined()
  expect(screen.getByText(/Missing from the register means nobody reported this building/)).toBeDefined()
  expect(screen.getByText('This is a list to check on site, not a list of findings.')).toBeDefined()
})

// Ta lista najlatwiej w calej aplikacji zsuwa sie z „model cos widzi na zdjeciu"
// na „wykryto azbest".
it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const full = renderList({ total: 120 })
  expect(full.container.textContent ?? '').not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)

  const empty = renderList({ roofs: [], total: 0 })
  expect(empty.container.textContent ?? '').not.toMatch(/detected asbestos|asbestos-free|no asbestos|safe|clean roof/i)
})

// Kropka nosi ten sam token, ktorym mapa maluje obrys tego dachu; czerwien zostaje przy rejestrze,
// a zielen jest zakazana, bo znaczylaby „czysty dach".
it('znaczy wiersze kolorem podejrzenia, nie czerwienia rejestru', () => {
  renderList()

  const dots = screen.getAllByTestId('flagged-roof-dot')

  expect(dots).toHaveLength(3)
  for (const dot of dots) {
    expect(dot.className).toContain('bg-suspected')
    expect(dot.className).not.toContain('bg-listed')
  }
})
