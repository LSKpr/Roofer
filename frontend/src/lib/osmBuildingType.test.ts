import { expect, it } from 'vitest'
import { buildingTypeLabel } from './osmBuildingType'

it('tlumaczy znany rodzaj i zostawia obok surowy tag', () => {
  expect(buildingTypeLabel('house')).toBe('dom jednorodzinny · house')
  expect(buildingTypeLabel('outbuilding')).toBe('budynek gospodarczy · outbuilding')
  expect(buildingTypeLabel('garage')).toBe('garaż · garage')
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
