import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App'
import type { Health } from './api/client'

vi.mock('maplibre-gl', () => ({
  Map: class {
    addControl() {}
    remove() {}
  },
  NavigationControl: class {},
  ScaleControl: class {},
}))

function stubHealth(status: number, body: Health | Record<string, never>) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status, json: async () => body }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('shows the PostGIS version once the backend answers', async () => {
  stubHealth(200, { status: 'ok', database: 'ok', postgis: '3.5.1', detail: null })

  render(<App />)

  expect(await screen.findByText(/PostGIS 3\.5\.1/)).toBeDefined()
})

it('says the database is missing instead of pretending everything is fine', async () => {
  stubHealth(503, { status: 'degraded', database: 'unavailable', postgis: null, detail: 'connection refused' })

  render(<App />)

  expect(await screen.findByText(/Backend bez bazy: connection refused/)).toBeDefined()
})

it('reports an unreachable backend', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Failed to fetch')))

  render(<App />)

  expect(await screen.findByText(/Backend niedostepny: Failed to fetch/)).toBeDefined()
})
