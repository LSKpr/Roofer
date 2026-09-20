import { useEffect, useState } from 'react'
import { fetchHealth, type Health } from './api/client'
import { MapView } from './map/MapView'

type BackendState =
  | { kind: 'checking' }
  | { kind: 'answered'; health: Health }
  | { kind: 'unreachable'; message: string }

function statusLabel(state: BackendState): { text: string; dot: string } {
  if (state.kind === 'checking') return { text: 'Backend: sprawdzam…', dot: 'bg-slate-400' }
  if (state.kind === 'unreachable') return { text: `Backend niedostepny: ${state.message}`, dot: 'bg-red-500' }
  if (state.health.status === 'ok') return { text: `Backend ok · PostGIS ${state.health.postgis}`, dot: 'bg-emerald-500' }
  return { text: `Backend bez bazy: ${state.health.detail ?? 'brak szczegolow'}`, dot: 'bg-amber-500' }
}

export function App() {
  const [state, setState] = useState<BackendState>({ kind: 'checking' })

  useEffect(() => {
    let current = true
    fetchHealth()
      .then((health) => current && setState({ kind: 'answered', health }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'nieznany blad'
        return current && setState({ kind: 'unreachable', message })
      })
    return () => {
      current = false
    }
  }, [])

  const status = statusLabel(state)

  return (
    <div className="flex h-full flex-col bg-slate-900 text-slate-100">
      <header className="flex items-center justify-between gap-4 border-b border-slate-700 px-4 py-3">
        <div>
          <h1 className="text-lg font-semibold">Roofer</h1>
          <p className="text-xs text-slate-400">Rejestr azbestu i budynki OSM na jednej mapie</p>
        </div>
        <p className="flex items-center gap-2 text-xs text-slate-300">
          <span className={`inline-block h-2 w-2 rounded-full ${status.dot}`} />
          {status.text}
        </p>
      </header>
      <main className="min-h-0 flex-1">
        <MapView />
      </main>
    </div>
  )
}
