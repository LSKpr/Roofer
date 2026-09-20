import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { roofImageUrl, type SuspectedRoof } from '../api/client'
import { FlaggedRoofs } from './FlaggedRoofs'

function aRoof(id: number, probability: number, areaM2 = 150): SuspectedRoof {
  return { id, probability, listed: false, areaM2, geometry: null }
}

/** Trzy dachy z prawdziwego przebiegu, juz posortowane — tak, jak komponent je dostaje. */
const ROOFS: SuspectedRoof[] = [aRoof(200, 0.91, 163), aRoof(201, 0.72, 150), aRoof(202, 0.66, 181.5)]

/** Krawedz kadru miniatury. Wpisana liczba, bo to ona jest decyzja pilnowana tym testem. */
const THUMBNAIL_SIZE = 128

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

function section(): HTMLElement {
  return screen.getByTestId('flagged-roofs')
}

/** Kafelki szukamy tak, jak znalazlby je uzytkownik klawiatury: to przyciski w tej sekcji. */
function tiles(): HTMLElement[] {
  return within(section()).getAllByRole('button')
}

/** Miniatury: kazdy kadr ma `alt` z identyfikatorem, wiec czytnik ekranu widzi je jako obrazy. */
function photos(): HTMLElement[] {
  return within(section()).getAllByRole('img')
}

it('na kafelku podaje ocene, powierzchnie dachu i identyfikator OSM', () => {
  renderList({ roofs: [aRoof(200, 0.91, 163)] })

  expect(screen.getByText('91%')).toBeDefined()
  expect(screen.getByText('163 m²')).toBeDefined()
  expect(screen.getByText('OSM 200')).toBeDefined()
})

// Ocena jest kluczem sortowania, wiec musi byc czytelna bez szukania: szeryfowa, jak liczby
// prowadzace w calym panelu.
it('wyroznia ocene, bo to ona ustawia kolejnosc siatki', () => {
  renderList({ roofs: [aRoof(200, 0.91, 163)] })

  expect(screen.getByText('91%').className).toContain('font-display')
})

// Sortuje `selectFlaggedNotListed`, nie komponent: gdyby sortowal oba, kolejnosc na ekranie
// zalezalaby od tego, ktory z nich ostatnio zmieniono.
it('pokazuje kafelki w kolejnosci, w ktorej je dostal', () => {
  renderList({ roofs: [aRoof(300, 0.55), aRoof(301, 0.91), aRoof(302, 0.7)] })

  expect(tiles().map((tile) => tile.textContent)).toEqual([
    '55%150 m²OSM 300',
    '91%150 m²OSM 301',
    '70%150 m²OSM 302',
  ])
})

// Kadr jest dowodem tej sekcji, wiec musi pochodzic z tego samego adresu, ktorym cala aplikacja
// adresuje ten dach — i przez funkcje z klienta API, zeby sciezka zyla w jednym miejscu.
it('bierze miniature dokladnie tego dachu, przez funkcje z klienta API', () => {
  renderList({ roofs: [aRoof(200, 0.91, 163)] })

  const src = photos()[0].getAttribute('src')

  expect(src).toBe(roofImageUrl(200, THUMBNAIL_SIZE))
  expect(src).toContain('/api/buildings/200/roof.png?size=128')
})

it('kazdy kafelek pokazuje kadr swojego dachu, a nie jeden wspolny', () => {
  renderList()

  expect(photos().map((photo) => photo.getAttribute('src'))).toEqual([
    roofImageUrl(200, THUMBNAIL_SIZE),
    roofImageUrl(201, THUMBNAIL_SIZE),
    roofImageUrl(202, THUMBNAIL_SIZE),
  ])
})

// Dwadziescia piec kadrow naraz idzie do naszego backendu, ktory ma wlasny ogranicznik do GUGiK:
// leniwe wczytywanie zostawia przegladarce decyzje, o ktore z nich zapytac teraz.
it('wczytuje kadry leniwie', () => {
  renderList()

  for (const photo of photos()) expect(photo.getAttribute('loading')).toBe('lazy')
})

it('wola onPick z identyfikatorem klikniętego dachu', () => {
  const onPick = vi.fn()
  renderList({ onPick })

  fireEvent.click(screen.getByText('OSM 202'))

  expect(onPick).toHaveBeenCalledTimes(1)
  expect(onPick).toHaveBeenCalledWith(202)
})

it('klikalny jest caly kafelek, a nie zdjecie ani numer pod nim', () => {
  const onPick = vi.fn()
  renderList({ onPick })

  expect(tiles()).toHaveLength(3)
  for (const tile of tiles()) expect(tile.getAttribute('type')).toBe('button')

  fireEvent.click(tiles()[0])

  expect(onPick).toHaveBeenCalledWith(200)
})

// GUGiK czasem nie oddaje kadru (503 z backendu). Dach bez zdjecia jest nadal dachem do
// sprawdzenia, wiec nie wolno mu wypasc z siatki razem ze zdjeciem.
it('brak zdjecia nie usuwa dachu z siatki: zostaje ocena, powierzchnia i klikalnosc', () => {
  const onPick = vi.fn()
  renderList({ roofs: [aRoof(200, 0.91, 163)], onPick })

  fireEvent.error(photos()[0])

  expect(within(section()).queryAllByRole('img')).toHaveLength(0)
  expect(screen.getByText('Aerial imagery unavailable')).toBeDefined()
  expect(tiles()).toHaveLength(1)
  expect(screen.getByText('91%')).toBeDefined()
  expect(screen.getByText('163 m²')).toBeDefined()

  fireEvent.click(tiles()[0])

  expect(onPick).toHaveBeenCalledWith(200)
})

it('jeden brakujacy kadr nie rusza pozostalych kafelkow', () => {
  renderList()

  fireEvent.error(photos()[1])

  expect(tiles()).toHaveLength(3)
  expect(photos()).toHaveLength(2)
  expect(screen.getAllByText('Aerial imagery unavailable')).toHaveLength(1)
})

// Ocena pochodzi ze zdjecia Google Satellite z zoomu 20, a kadr w siatce z ortofotomapy GUGiK:
// dwa zrodla i dwa momenty. Bez tego zdania ktos rozstrzyga o modelu zdjeciem, ktorego model
// nie widzial.
it('mowi, ze kadry sa z ortofotomapy GUGiK, a model ocenial inne zdjecie', () => {
  renderList()

  expect(screen.getByText(/thumbnails come from the GUGiK orthophoto/i)).toBeDefined()
  expect(screen.getByText(/as it looked during the aerial survey/)).toBeDefined()
  expect(screen.getByText(/not the Google Satellite frame at zoom 20 that the model scored/)).toBeDefined()
})

// Identyfikator jest adresem dachu w reszcie aplikacji, wiec czytnik ekranu musi go dostac —
// takze razem z samym kadrem, nie tylko w podpisie pod nim.
it('podaje identyfikator OSM czytnikowi ekranu, nie tylko oku', () => {
  renderList({ roofs: [aRoof(200, 0.91, 163)] })

  expect(screen.getByAltText('Roof of building 200')).toBeDefined()
  expect(within(tiles()[0]).getByText('OSM 200')).toBeDefined()
})

// Liczba w naglowku ma opisywac caly obszar, bo to ona jest liczba prowadzaca sekcji modelu.
it('w naglowku liczy caly obszar, a nie widoczne kafelki', () => {
  renderList({ total: 120, limit: 2 })

  expect(screen.getByText('Not in the register, flagged by the model (120)')).toBeDefined()
  expect(tiles()).toHaveLength(2)
})

it('przycina liste do limitu i mowi, ile z ilu pokazuje', () => {
  const many = Array.from({ length: 30 }, (_, index) => aRoof(400 + index, 0.8))

  renderList({ roofs: many, limit: 25 })

  expect(tiles()).toHaveLength(25)
  expect(screen.getByText(/showing 25 of 30 roofs/)).toBeDefined()
  expect(screen.getByText(/the numbers above cover the whole area/)).toBeDefined()
})

// Limit jest jednoczesnie gorna liczba zdjec, o ktore siatka pyta naraz nasz backend.
it('bez podanego limitu pokazuje najwyzej dwadziescia piec kafelkow i tyle samo kadrow', () => {
  const many = Array.from({ length: 26 }, (_, index) => aRoof(500 + index, 0.8))

  renderList({ roofs: many })

  expect(tiles()).toHaveLength(25)
  expect(photos()).toHaveLength(25)
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

  expect(tiles()).toHaveLength(3)
  expect(screen.getByText(/showing 3 of 120 roofs/)).toBeDefined()
})

// Pustka wygladalaby jak „nic tu nie ma", a to jest tylko stan progu.
it('pusta liste tlumaczy zdaniem, a nie pustym miejscem', () => {
  renderList({ roofs: [], total: 0 })

  expect(screen.getByText(/No roof here is both above the threshold and missing from the register/)).toBeDefined()
  expect(screen.getByText(/Lower the threshold to see roofs the model scored lower/)).toBeDefined()
  expect(within(section()).queryAllByRole('button')).toHaveLength(0)
  expect(within(section()).queryAllByRole('img')).toHaveLength(0)
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

// Te zdania dotycza calej sekcji, wiec nie wolno im zniknac razem z kafelkami.
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
it('znaczy kafelki kolorem podejrzenia, nie czerwienia rejestru', () => {
  renderList()

  const dots = screen.getAllByTestId('flagged-roof-dot')

  expect(dots).toHaveLength(3)
  for (const dot of dots) {
    expect(dot.className).toContain('bg-suspected')
    expect(dot.className).not.toContain('bg-listed')
  }
})
