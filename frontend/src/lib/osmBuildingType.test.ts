import { expect, it } from 'vitest'
import { buildingTypeLabel, buildingTypeName } from './osmBuildingType'

it('opisuje rodzaj i zostawia obok surowy tag', () => {
  expect(buildingTypeLabel('house')).toBe('single-family house · house')
  expect(buildingTypeLabel('farm_auxiliary')).toBe('farm outbuilding · farm_auxiliary')
  expect(buildingTypeLabel('sty')).toBe('pigsty · sty')
})

// Klucze OSM sa angielskie, wiec przy angielskim interfejsie czesc etykiet jest tagiem: „garage ·
// garage" wygladaloby w karcie jak usterka, a tag i tak jest w calosci widoczny w etykiecie.
it('nie doklada tagu, gdy etykieta jest z nim identyczna', () => {
  expect(buildingTypeLabel('garage')).toBe('garage')
  expect(buildingTypeLabel('outbuilding')).toBe('outbuilding')
  expect(buildingTypeLabel('cowshed')).toBe('cowshed')
  expect(buildingTypeLabel('barn')).toBe('barn')
})

it('nieznanego rodzaju nie tlumaczy na sile', () => {
  expect(buildingTypeLabel('pumping_station')).toBe('pumping_station')
})

it('brak rodzaju to brak wiersza, a nie puste pole', () => {
  expect(buildingTypeLabel(null)).toBeNull()
  expect(buildingTypeLabel(undefined)).toBeNull()
  // Backend zapisuje pusty ciag jako NULL, ale interfejs nie moze na to liczyc.
  expect(buildingTypeLabel('   ')).toBeNull()
})

// Naglowek karty bierze sama nazwe, wiec musi ja dostac takze dla tagow, ktore sa juz angielskie.
it('sama nazwa rodzaju nigdy nie zawiera separatora z tagiem', () => {
  expect(buildingTypeName('semidetached_house')).toBe('semi-detached house')
  expect(buildingTypeName('garage')).toBe('garage')
  expect(buildingTypeName('pumping_station')).toBe('pumping_station')
  expect(buildingTypeName(null)).toBeNull()
})
