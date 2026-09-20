import { useEffect, useState } from 'react'
import { fetchBuilding, type Building } from '../api/client'

export type BuildingState = {
  building: Building | null
  loading: boolean
  error: string | null
}

const IDLE: BuildingState = { building: null, loading: false, error: null }
const LOADING: BuildingState = { building: null, loading: true, error: null }

type Answer = { id: number; state: BuildingState }

/**
 * Szczegoly wybranego budynku.
 *
 * Stany „nic nie wybrano" i „wczytuje" sa wyliczane w trakcie renderu z porownania wybranego
 * identyfikatora z identyfikatorem ostatniej odpowiedzi. Ustawianie ich przez setState w efekcie
 * byloby kaskada renderow i przez chwile pokazywaloby dane poprzedniego budynku.
 */
export function useBuilding(id: number | null): BuildingState {
  const [answer, setAnswer] = useState<Answer | null>(null)

  useEffect(() => {
    if (id === null) return
    let current = true
    fetchBuilding(id)
      .then((building) => current && setAnswer({ id, state: { building, loading: false, error: null } }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'Nieznany blad'
        return current && setAnswer({ id, state: { building: null, loading: false, error: message } })
      })
    return () => {
      current = false
    }
  }, [id])

  if (id === null) return IDLE
  return answer?.id === id ? answer.state : LOADING
}
