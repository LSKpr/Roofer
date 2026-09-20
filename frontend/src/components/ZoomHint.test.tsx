import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ZoomHint } from './ZoomHint'
import { POINT_MIN_ZOOM, POLYGON_MIN_ZOOM } from '../map/layers'

it('says nothing when outlines are on screen', () => {
  render(<ZoomHint zoom={POLYGON_MIN_ZOOM} />)

  expect(screen.queryByText(/Przybliż/)).toBeNull()
})

it('explains that the heat shows density of reports, not single buildings', () => {
  render(<ZoomHint zoom={POLYGON_MIN_ZOOM - 1} />)

  // „Punkty budynkow" byloby teraz nieprawda: kafel niesie komorki siatki z liczba zgloszen,
  // a nie pojedyncze dachy, wiec klikniecie w cieplo nie wskazuje zadnego budynku.
  expect(screen.getByText(/zagęszczenie zgłoszeń w rejestrze, nie pojedyncze budynki/)).toBeDefined()
})

it('asks for more zoom when the map serves nothing at all', () => {
  render(<ZoomHint zoom={POINT_MIN_ZOOM - 1} />)

  expect(screen.getByText('Przybliż mapę, aby zobaczyć budynki.')).toBeDefined()
})
