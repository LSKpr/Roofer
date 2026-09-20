import { useCallback, useRef, useState } from 'react'
import { fetchAreaScan, type AreaScan, type Bounds } from '../api/client'

export type AreaScanState = {
  scan: AreaScan | null
  loading: boolean
  error: string | null
  /** Zleca skan zaznaczonego prostokata. Kolejne wywolanie uniewaznia poprzednie. */
  run: (bounds: Bounds) => void
  clear: () => void
}

/** Odpowiedz opisana numerem zlecenia, ktore ja wywolalo. */
type Answer = { request: number; scan: AreaScan | null; error: string | null }

/**
 * Skan obszaru zlecany zdarzeniem — narysowaniem prostokata, nie zmiana propsa.
 *
 * `scan`, `loading` i `error` sa wyliczane w trakcie renderu z porownania numeru ostatniego
 * zlecenia z numerem odpowiedzi, tak samo jak w useBuilding i usePlaceSearch. Ustawianie ich
 * przez setState w efekcie byloby kaskada renderow i przez chwile pokazywaloby wynik
 * poprzedniego zaznaczenia; `setState` w `run` jest czym innym — to reakcja na zdarzenie.
 *
 * Porzucona odpowiedz nie moze nadpisac nowszej, dlatego numer ostatniego zlecenia siedzi
 * dodatkowo w `useRef`: gdyby wolniejszy pierwszy skan wrocil po szybszym drugim, samo
 * porownanie w renderze zamieniloby gotowy wynik na „wczytuje" bez konca.
 */
export function useAreaScan(): AreaScanState {
  const [request, setRequest] = useState(0)
  const [answer, setAnswer] = useState<Answer | null>(null)
  // Numer zlecenia, ktorego odpowiedz wolno jeszcze przyjac. `clear` podbija go, zeby
  // porzucic skan w locie.
  const latest = useRef(0)

  const run = useCallback((bounds: Bounds) => {
    const id = latest.current + 1
    latest.current = id
    setRequest(id)
    const settle = (next: Answer) => {
      if (latest.current === id) setAnswer(next)
    }
    fetchAreaScan(bounds)
      .then((scan) => settle({ request: id, scan, error: null }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'Could not scan the area.'
        settle({ request: id, scan: null, error: message })
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
    scan: fresh?.scan ?? null,
    loading: request !== 0 && fresh === null,
    error: fresh?.error ?? null,
    run,
    clear,
  }
}
