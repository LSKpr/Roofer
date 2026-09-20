import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ZoomHint } from './ZoomHint'
import { POINT_MIN_ZOOM, POLYGON_MIN_ZOOM } from '../map/layers'

it('says nothing when outlines are on screen', () => {
  render(<ZoomHint zoom={POLYGON_MIN_ZOOM} />)

  expect(screen.queryByText(/Przybliż/)).toBeNull()
})

it('explains that only listed buildings are visible as points', () => {
  render(<ZoomHint zoom={POLYGON_MIN_ZOOM - 1} />)

  expect(screen.getByText(/punkty budynków zgłoszonych/)).toBeDefined()
})

it('asks for more zoom when the map serves nothing at all', () => {
  render(<ZoomHint zoom={POINT_MIN_ZOOM - 1} />)

  expect(screen.getByText('Przybliż mapę, aby zobaczyć budynki.')).toBeDefined()
})
