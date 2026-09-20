import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { INITIAL_CENTER, INITIAL_ZOOM, basemapStyle } from './basemap'
import { MapView } from './MapView'

const constructed: unknown[] = []
const added: unknown[] = []
const removed = vi.fn()

vi.mock('maplibre-gl', () => ({
  Map: class {
    constructor(options: unknown) {
      constructed.push(options)
    }
    addControl(control: unknown) {
      added.push(control)
    }
    remove = removed
  },
  NavigationControl: class {},
  ScaleControl: class {},
}))

it('creates one map with the configured style and viewport', () => {
  render(<MapView />)

  expect(screen.getByTestId('map')).toBeDefined()
  expect(constructed).toHaveLength(1)
  expect(constructed[0]).toMatchObject({ style: basemapStyle, center: INITIAL_CENTER, zoom: INITIAL_ZOOM })
  expect(added).toHaveLength(2)
})

it('removes the map when the component unmounts', () => {
  const view = render(<MapView />)
  view.unmount()

  expect(removed).toHaveBeenCalled()
})
