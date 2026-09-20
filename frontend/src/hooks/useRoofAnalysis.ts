import { useEffect, useState } from 'react'
import { fetchRoofAnalysis, type RoofAnalysis } from '../api/client'

export type RoofAnalysisState = {
  analysis: RoofAnalysis | null
  loading: boolean
  error: string | null
}

const IDLE: RoofAnalysisState = { analysis: null, loading: false, error: null }
const LOADING: RoofAnalysisState = { analysis: null, loading: true, error: null }

type Answer = { id: number; state: RoofAnalysisState }

/**
 * Ocena pokrycia dachu wybranego budynku.
 *
 * Stany „nic nie wybrano" i „wczytuje" sa wyliczane w trakcie renderu z porownania wybranego
 * identyfikatora z identyfikatorem ostatniej odpowiedzi — tak samo jak w useBuilding. Ustawianie
 * ich przez setState w efekcie byloby kaskada renderow i przez chwile pokazywaloby ocene
 * poprzedniego budynku, a tu jest to szkodliwe podwojnie: procent z innego dachu wyglada jak
 * wynik dla tego, ktory wlasnie klikniety.
 */
export function useRoofAnalysis(buildingId: number | null): RoofAnalysisState {
  const [answer, setAnswer] = useState<Answer | null>(null)

  useEffect(() => {
    if (buildingId === null) return
    // Porzucona odpowiedz nie moze nadpisac nowszej: sprzatanie efektu gasi ten znacznik,
    // wiec spozniony wynik poprzedniego budynku nie trafia nawet do stanu.
    let current = true
    fetchRoofAnalysis(buildingId)
      .then((analysis) => current && setAnswer({ id: buildingId, state: { analysis, loading: false, error: null } }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'Could not load the roof covering analysis.'
        return current && setAnswer({ id: buildingId, state: { analysis: null, loading: false, error: message } })
      })
    return () => {
      current = false
    }
  }, [buildingId])

  if (buildingId === null) return IDLE
  return answer?.id === buildingId ? answer.state : LOADING
}
