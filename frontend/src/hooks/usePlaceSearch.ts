import { useCallback, useEffect, useState } from 'react'
import { fetchPlaces, type Place } from '../api/client'

export type PlaceSearchState = {
  query: string
  setQuery: (query: string) => void
  results: Place[]
  loading: boolean
  error: string | null
  clear: () => void
}

/** Backend jest proxy do Nominatima z limitem jednego zapytania na sekunde dla calej uslugi. */
export const SEARCH_DEBOUNCE_MS = 400

/** Krotsza fraza zwraca pol wojewodztwa, wiec zapytanie o nia to zmarnowany limit. */
export const MIN_QUERY_LENGTH = 3

const NOTHING: Place[] = []

type Answer = { query: string; results: Place[]; error: string | null }

/**
 * Podpowiedzi miejsc z wyszukiwarki.
 *
 * Zapytanie leci dopiero SEARCH_DEBOUNCE_MS po ostatnim nacisnieciu klawisza — przy limicie
 * jednego zapytania na sekunde odpytywanie po kazdym znaku skonczyloby sie bledem 429
 * zamiast podpowiedziami.
 *
 * `results`, `loading` i `error` sa wyliczane w trakcie renderu z porownania aktualnej frazy
 * z fraza ostatniej odpowiedzi — tak samo jak w useBuilding. Ustawianie ich przez setState
 * w efekcie byloby kaskada renderow i przez chwile pokazywaloby podpowiedzi do poprzedniej
 * frazy; tutaj odpowiedz na porzucona fraze po prostu nigdy nie jest uznawana za aktualna.
 */
export function usePlaceSearch(): PlaceSearchState {
  const [query, setQuery] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)

  const trimmed = query.trim()
  const asks = trimmed.length >= MIN_QUERY_LENGTH

  useEffect(() => {
    if (!asks) return
    // `current` odcina odpowiedz na fraze, ktorej uzytkownik juz nie widzi w polu.
    let current = true
    const timer = setTimeout(() => {
      fetchPlaces(trimmed)
        .then((results) => current && setAnswer({ query: trimmed, results, error: null }))
        .catch((error: unknown) => {
          const message = error instanceof Error ? error.message : 'Nieznany blad wyszukiwarki'
          return current && setAnswer({ query: trimmed, results: NOTHING, error: message })
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [asks, trimmed])

  const clear = useCallback(() => {
    setQuery('')
    setAnswer(null)
  }, [])

  // Odpowiedz do innej frazy nie jest wynikiem dla tej frazy, wiec nie jest nawet czytana.
  const fresh = answer !== null && answer.query === trimmed ? answer : null

  return {
    query,
    setQuery,
    results: asks && fresh ? fresh.results : NOTHING,
    loading: asks && fresh === null,
    error: fresh?.error ?? null,
    clear,
  }
}
