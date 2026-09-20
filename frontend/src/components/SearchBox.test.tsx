import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SearchBox } from './SearchBox'
import { SEARCH_DEBOUNCE_MS } from '../hooks/usePlaceSearch'
import { fetchPlaces, type Place } from '../api/client'

const ZWOLEN: Place = {
  label: 'Zwoleń, gmina Zwoleń, powiat zwoleński, województwo mazowieckie, 26-700, Polska',
  lat: 51.3557,
  lng: 21.5919,
  bbox: [51.33, 21.56, 51.38, 21.62],
  kind: 'town',
}

const ZWOLENSKA: Place = {
  label: 'Zwoleńska, Wawer, Warszawa, województwo mazowieckie, 04-761, Polska',
  lat: 52.1707,
  lng: 21.1543,
  bbox: null,
  kind: 'road',
}

function okResponse(results: Place[]): Response {
  return { status: 200, json: async () => ({ results }) } as unknown as Response
}

function stubFetch(status: number, results: Place[] = []) {
  const response =
    status === 200 ? okResponse(results) : ({ status, json: async () => ({}) } as unknown as Response)
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(response))
}

/** Podpowiedzi pojawiaja sie po debounce, wiec zegar trzeba przesunac recznie. */
async function typeAndSettle(value: string) {
  fireEvent.change(screen.getByRole('combobox'), { target: { value } })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('shows suggestions only after the debounce', async () => {
  stubFetch(200, [ZWOLEN, ZWOLENSKA])
  render(<SearchBox onPick={() => {}} />)

  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'zwole' } })
  expect(screen.getByText('Searching…')).toBeDefined()
  expect(screen.queryAllByRole('option')).toHaveLength(0)

  await act(async () => {
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
  })

  expect(screen.queryAllByRole('option')).toHaveLength(2)
  expect(screen.getByText('Zwoleń')).toBeDefined()
})

it('splits the long Nominatim label into a name and its context', async () => {
  stubFetch(200, [ZWOLEN])
  render(<SearchBox onPick={() => {}} />)

  await typeAndSettle('zwole')

  expect(screen.getByText('Zwoleń')).toBeDefined()
  expect(screen.getByText(/gmina Zwoleń, powiat zwoleński/)).toBeDefined()
  expect(screen.getByText('town')).toBeDefined()
})

it('asks for nothing while the phrase is shorter than three characters', async () => {
  stubFetch(200, [ZWOLEN])
  render(<SearchBox onPick={() => {}} />)

  await typeAndSettle('zw')

  expect(screen.queryAllByRole('option')).toHaveLength(0)
  expect(screen.queryByText('No results')).toBeNull()
})

it('hands the whole place to onPick when a suggestion is clicked', async () => {
  stubFetch(200, [ZWOLEN, ZWOLENSKA])
  const onPick = vi.fn()
  render(<SearchBox onPick={onPick} />)

  await typeAndSettle('zwole')
  fireEvent.click(screen.getAllByRole('option')[0])

  expect(onPick).toHaveBeenCalledTimes(1)
  expect(onPick).toHaveBeenCalledWith(ZWOLEN)
  expect(screen.queryAllByRole('option')).toHaveLength(0)
})

it('moves the selection with arrows and picks it with Enter', async () => {
  stubFetch(200, [ZWOLEN, ZWOLENSKA])
  const onPick = vi.fn()
  render(<SearchBox onPick={onPick} />)
  await typeAndSettle('zwole')

  const input = screen.getByRole('combobox')
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  fireEvent.keyDown(input, { key: 'ArrowDown' })

  const options = screen.getAllByRole('option')
  expect(options[0].getAttribute('aria-selected')).toBe('false')
  expect(options[1].getAttribute('aria-selected')).toBe('true')
  expect(input.getAttribute('aria-activedescendant')).toBe(options[1].getAttribute('id'))

  fireEvent.keyDown(input, { key: 'Enter' })

  expect(onPick).toHaveBeenCalledWith(ZWOLENSKA)
})

it('wraps the selection around with the up arrow', async () => {
  stubFetch(200, [ZWOLEN, ZWOLENSKA])
  const onPick = vi.fn()
  render(<SearchBox onPick={onPick} />)
  await typeAndSettle('zwole')

  fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowUp' })
  fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' })

  expect(onPick).toHaveBeenCalledWith(ZWOLENSKA)
})

it('collapses the list on Escape and drops the selection', async () => {
  stubFetch(200, [ZWOLEN, ZWOLENSKA])
  const onPick = vi.fn()
  render(<SearchBox onPick={onPick} />)
  await typeAndSettle('zwole')

  const input = screen.getByRole('combobox')
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  fireEvent.keyDown(input, { key: 'Escape' })

  expect(screen.queryAllByRole('option')).toHaveLength(0)
  expect(input.getAttribute('aria-expanded')).toBe('false')
  expect(input.getAttribute('aria-activedescendant')).toBeNull()

  fireEvent.keyDown(input, { key: 'Enter' })

  expect(onPick).not.toHaveBeenCalled()
})

it('empties the field with the clear button', async () => {
  stubFetch(200, [ZWOLEN])
  render(<SearchBox onPick={() => {}} />)
  await typeAndSettle('zwole')

  fireEvent.click(screen.getByLabelText('Clear'))

  expect(screen.queryByDisplayValue('zwole')).toBeNull()
  expect(screen.queryByLabelText('Clear')).toBeNull()
  expect(screen.queryAllByRole('option')).toHaveLength(0)
})

it('shows the error message from the hook', async () => {
  stubFetch(429)
  render(<SearchBox onPick={() => {}} />)

  await typeAndSettle('zwole')

  // Tresc komunikatu nalezy do api/client.ts, wiec bierzemy ja stamtad zamiast trzymac tu
  // druga kopie zdania: test pilnuje, ze uzytkownik widzi dokladnie to, co zglosila warstwa
  // danych, a nie ze ktos wpisal w panelu wlasny tekst.
  const message = await fetchPlaces('zwole').then(
    () => 'fetchPlaces nie zglosil bledu przy 429',
    (cause: Error) => cause.message,
  )

  expect(screen.getByText('Error')).toBeDefined()
  expect(screen.getByText(message)).toBeDefined()
  expect(screen.queryAllByRole('option')).toHaveLength(0)
})

it('says plainly that a long enough phrase found nothing', async () => {
  stubFetch(200, [])
  render(<SearchBox onPick={() => {}} />)

  await typeAndSettle('qqqqq')

  expect(screen.getByText('No results')).toBeDefined()
})
