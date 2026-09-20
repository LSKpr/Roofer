import { useCallback, useRef, useState } from 'react'
import { fetchAreaAnalysis, type AreaAnalysis, type Bounds } from '../api/client'

export type AreaAnalysisState = {
  analysis: AreaAnalysis | null
  loading: boolean
  error: string | null
  /** Zleca ocene modelu dla prostokata. Kolejne wywolanie uniewaznia poprzednie. */
  run: (bounds: Bounds) => void
  clear: () => void
}

/** Odpowiedz opisana numerem zlecenia, ktore ja wywolalo. */
type Answer = { request: number; analysis: AreaAnalysis | null; error: string | null }

/**
 * Ocena modelu dla obszaru, zlecana zdarzeniem — kliknieciem przycisku, nie zmiana propsa.
 *
 * Budowa jest ta sama co w useAreaScan: `analysis`, `loading` i `error` sa wyliczane w trakcie
 * renderu z porownania numeru ostatniego zlecenia z numerem odpowiedzi, a numer ostatniego
 * zlecenia siedzi dodatkowo w `useRef`, zeby porzucona odpowiedz nie nadpisala nowszej. Model
 * liczy kilka sekund, wiec wyscig jest tu realny: uzytkownik zdazy zaznaczyc drugi obszar,
 * zanim wroci pierwsza ocena, a wynik z poprzedniego prostokata opisywalby budynki, ktorych
 * na ekranie juz nie ma.
 */
export function useAreaAnalysis(): AreaAnalysisState {
  const [request, setRequest] = useState(0)
  const [answer, setAnswer] = useState<Answer | null>(null)
  // Numer zlecenia, ktorego odpowiedz wolno jeszcze przyjac. `clear` podbija go, zeby
  // porzucic ocene w locie.
  const latest = useRef(0)

  const run = useCallback((bounds: Bounds) => {
    const id = latest.current + 1
    latest.current = id
    setRequest(id)
    const settle = (next: Answer) => {
      if (latest.current === id) setAnswer(next)
    }
    fetchAreaAnalysis(bounds)
      .then((analysis) => settle({ request: id, analysis, error: null }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'Could not analyse the area.'
        settle({ request: id, analysis: null, error: message })
      })
  }, [])

  const clear = useCallback(() => {
    latest.current += 1
    setRequest(0)
    setAnswer(null)
  }, [])

  // Odpowiedz na inne zlecenie nie jest wynikiem tego zlecenia, wiec nie jest nawet czytana.
  const fresh = answer !== null && answer.request === request ? answer : null

  return {
    analysis: fresh?.analysis ?? null,
    loading: request !== 0 && fresh === null,
    error: fresh?.error ?? null,
    run,
    clear,
  }
}
