import assert from 'node:assert/strict'
import { test } from 'node:test'

import { render, screen } from '@testing-library/react'

import HomePage from '../src/app/page'

test('strona glowna informuje, ze mapy jeszcze nie ma', () => {
  render(<HomePage />)
  assert.ok(screen.getByText('Mapa pojawi się w fazie F3.'))
})
