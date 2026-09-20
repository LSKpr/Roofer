import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { roofImageUrl, type RoofImage } from '../api/client'
import { RoofPhoto } from './RoofPhoto'

function photo() {
  return screen.getByAltText(/roof of building/i)
}

/** Wycinek z dysku: eksport GUGiK 5 cm ze stala ramka 12,8 m i znanym dniem nalotu. */
const LOCAL: RoofImage = { source: 'local', gsdM: 0.05, frameM: 12.8, acquiredOn: '2023-12-05' }

/** Kadr z WMS-a: daty nalotu ani rodzimej rozdzielczosci tamta usluga nie podaje. */
const WMS: RoofImage = { source: 'wms', gsdM: null, frameM: null, acquiredOn: null }

/** Zdanie, ktore stoi w podpisie przy obu zrodlach — sprawdzane dokladnym brzmieniem. */
const SURVEY_NOTE =
  'The image shows the roof as it looked during the aerial survey. It does not confirm what the covering is made of, nor what state the roof is in today.'

/** Caly dotychczasowy podpis: to zdanie i atrybucja, nic wiecej. */
const CAPTION_TODAY = `${SURVEY_NOTE}Aerial imagery: GUGiK / Geoportal.gov.pl`

/** Nazwa miesiaca albo czterocyfrowy rok — cokolwiek, co czyta sie pod zdjeciem jako data. */
const ANY_DATE =
  /January|February|March|April|May|June|July|August|September|October|November|December|\d{4}/

function captionText(): string {
  return screen.getByTestId('roof-photo').querySelector('figcaption')?.textContent ?? ''
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

  expect(screen.getByText('Aerial imagery: GUGiK / Geoportal.gov.pl')).toBeDefined()
})

it('mowi, czego zdjecie nie dowodzi', () => {
  render(<RoofPhoto buildingId={7} />)

  expect(screen.getByText(/during the aerial survey/)).toBeDefined()
  expect(screen.getByText(/does not confirm what the covering is made of/)).toBeDefined()
})

it('zamienia niedostepne ortofoto na komunikat, nie na pusta ramke', () => {
  render(<RoofPhoto buildingId={7} />)

  fireEvent.error(photo())

  expect(screen.getByText('Aerial imagery unavailable')).toBeDefined()
  expect(screen.queryByAltText(/roof of building/i)).toBeNull()
  expect(screen.getByTestId('roof-photo').getAttribute('data-state')).toBe('unavailable')
})

it('atrybucja zostaje takze wtedy, gdy zdjecia nie ma', () => {
  render(<RoofPhoto buildingId={7} />)

  fireEvent.error(photo())

  expect(screen.getByText('Aerial imagery: GUGiK / Geoportal.gov.pl')).toBeDefined()
})

it('po wczytaniu odslania zdjecie', () => {
  render(<RoofPhoto buildingId={7} />)

  fireEvent.load(photo())

  expect(screen.getByTestId('roof-photo').getAttribute('data-state')).toBe('ready')
})

it('nie uzywa slownictwa sugerujacego pomiar azbestu', () => {
  const view = render(<RoofPhoto buildingId={7} />)

  // Podpis mowi, czego zdjecie NIE dowodzi, wiec nie ma tu prawa padc ani „detected", ani zapewnienie
  // o czystym czy bezpiecznym dachu — kadr z nalotu nie rozstrzyga materialu pokrycia.
  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/detected|asbestos-free|no asbestos|safe|clean/i)
})

// Ten sam straznik przy dluzszym podpisie kadru z dysku: ostrzejsze zdjecie tym bardziej nie
// rozstrzyga, z czego jest pokrycie.
it('nie uzywa tego slownictwa takze przy kadrze z dysku', () => {
  const view = render(<RoofPhoto buildingId={7} roofImage={LOCAL} />)

  const text = view.container.textContent ?? ''
  expect(text).not.toMatch(/detected|asbestos-free|no asbestos|safe|clean/i)
})

it('przy kadrze z dysku podaje dzien nalotu i rozdzielczosc', () => {
  render(<RoofPhoto buildingId={7} roofImage={LOCAL} />)

  expect(screen.getByText('Flown on 5 December 2023, at 5 cm per pixel.')).toBeDefined()
  // Zdanie o tym, czego zdjecie nie dowodzi, zostaje prawda takze dla tego kadru.
  expect(screen.getByText(SURVEY_NOTE)).toBeDefined()
})

// Najwazniejsze zastrzezenie tego kadru: ramka jest stala, wiec dluzszy dach jest przyciety.
// Bez tego zdania uzytkownik odczyta z obrazka, ze budynek jest mniejszy, niz jest.
it('ostrzega, ze stala ramka 12,8 m przycina dluzszy dach', () => {
  render(<RoofPhoto buildingId={7} roofImage={LOCAL} />)

  expect(screen.getByText(/fixed 12\.8 m square/)).toBeDefined()
  expect(screen.getByText(/roof longer than 12\.8 m runs past the edge/)).toBeDefined()
  expect(screen.getByText(/looks smaller than it is/)).toBeDefined()
})

// Kadr z WMS-a liczymy wokol calego obrysu, wiec te dwa zdjecia nie sa tym samym — porownanie
// jednego z drugim bez tego zdania prowadzi do wniosku o wielkosci budynku wzietego z niczego.
it('mowi, ze kadr z WMS-a nie jest tym samym obrazem', () => {
  render(<RoofPhoto buildingId={7} roofImage={LOCAL} />)

  expect(screen.getByText(/square around the whole outline/)).toBeDefined()
})

// Data jest skladana z samego napisu `YYYY-MM-DD`, bez `new Date()`: inaczej strefa czasowa
// przegladarki przesuwalaby dzien nalotu i test przestalby byc deterministyczny.
it('formatuje date dnia nalotu z samego napisu', () => {
  render(<RoofPhoto buildingId={7} roofImage={{ ...LOCAL, acquiredOn: '2023-12-12' }} />)

  expect(screen.getByText(/Flown on 12 December 2023/)).toBeDefined()
})

it('nie wymysla daty z napisu, ktorego nie rozumie', () => {
  const view = render(<RoofPhoto buildingId={7} roofImage={{ ...LOCAL, acquiredOn: '12 grudnia 2023' }} />)

  // Zabraklo tylko daty: rozdzielczosc i ostrzezenie o ramce zostaja.
  expect(screen.getByText('Recorded at 5 cm per pixel.')).toBeDefined()
  expect(screen.getByText(/fixed 12\.8 m square/)).toBeDefined()
  expect(view.container.textContent ?? '').not.toMatch(/December/)
})

// Przy kadrze z WMS-a nie znamy ani daty nalotu, ani rodzimej rozdzielczosci, ani krawedzi kadru,
// wiec podpis musi zostac dokladnie taki, jaki byl — co do znaku.
it('przy kadrze z WMS-a zostawia dokladnie dotychczasowy podpis, bez daty', () => {
  render(<RoofPhoto buildingId={7} roofImage={WMS} />)

  expect(captionText()).toBe(CAPTION_TODAY)
  expect(captionText()).not.toMatch(ANY_DATE)
})

// Straznik samego warunku zrodla. O tym, co wiemy, rozstrzyga `source`, a nie to, ze jakas liczba
// przyszla w odpowiedzi: daty nalotu kadru z WMS-a nie znamy i nie wolno jej z niczego wyprowadzac.
it('nie bierze daty z kadru z WMS-a, nawet gdy liczby przyszly w odpowiedzi', () => {
  render(<RoofPhoto buildingId={7} roofImage={{ source: 'wms', gsdM: 0.05, frameM: 12.8, acquiredOn: '2023-12-05' }} />)

  expect(captionText()).toBe(CAPTION_TODAY)
  expect(captionText()).not.toMatch(ANY_DATE)
})

it('bez pola o zrodle kadru podpis jest taki sam jak przy WMS-ie', () => {
  render(<RoofPhoto buildingId={7} />)

  expect(captionText()).toBe(CAPTION_TODAY)
  expect(captionText()).not.toMatch(ANY_DATE)
})

it('pole ustawione na null tez nie dodaje niczego do podpisu', () => {
  render(<RoofPhoto buildingId={7} roofImage={null} />)

  expect(captionText()).toBe(CAPTION_TODAY)
})
