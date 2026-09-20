import type { RoofAnalysis as Analysis } from '../api/client'

type RoofAnalysisProps = {
  analysis: Analysis | null
  loading: boolean
  error: string | null
}

/**
 * Werdykt slownie, bo liczba bez zdania jest nieczytelna, a zdanie musi mowic o wygladzie
 * pokrycia, nie o azbescie: model widzi faliste, szare plyty, a nie material.
 */
const VERDICT_TEXT: Record<Analysis['verdict'], string> = {
  suspected: 'Possible corrugated grey covering (eternit type)',
  unlikely: 'The model does not see corrugated grey covering',
  unknown: 'Not known what the covering is',
}

/**
 * Znacznik werdyktu to kwadratowa kropka jak status rejestru w karcie, nigdy kolorowa plakietka.
 * Zielen nie wystepuje w ogole: znaczylaby „czysty dach", a model rozpoznaje tylko wyglad pokrycia.
 */
function dotClass(verdict: Analysis['verdict']): string {
  return verdict === 'suspected' ? 'bg-listed' : 'bg-not-listed'
}

/** Prawdopodobienstwo przychodzi z backendu jako ulamek 0–1. */
function percentLabel(probability: number): string {
  return `${Math.round(probability * 100)}%`
}

/**
 * Mikropodpis nad werdyktem mowi, skad wynik pochodzi.
 *
 * Dla `mock` jest to wymog, nie ozdoba: procent wymyslony na demo, pokazany jak wynik modelu,
 * bylby sfabrykowanym dowodem, a karta sluzy do decyzji urzedowych. Dlatego ostrzezenie stoi
 * przy werdykcie i ma kolor tekstu glownego, a nie mikropodpisu. Niedostepnosc modelu jest
 * spokojna — szarosc, bez czerwieni ostrzegawczej.
 */
function SourceNote({ source }: { source: Analysis['source'] }) {
  if (source === 'mock') {
    return (
      <p data-testid="analysis-mock-warning" className="label-micro border-b border-hairline pb-1.5 text-ink">
        Demonstration result · no model connected
      </p>
    )
  }
  if (source === 'unavailable') {
    return (
      <p data-testid="analysis-unavailable-note" className="label-micro border-b border-hairline pb-1.5">
        Analysis unavailable · the model did not respond
      </p>
    )
  }
  return null
}

/**
 * Sekcja „analiza pokrycia dachu" w karcie budynku: werdykt, prawdopodobienstwo i zastrzezenia.
 *
 * Komponent nie siega po siec i nie rysuje wlasnej ramki ani naglowka — wchodzi w karte pod
 * zdjeciem dachu, tak samo jak RoofPhoto, wiec ramke i naglowek daje karta.
 */
export function RoofAnalysis({ analysis, loading, error }: RoofAnalysisProps) {
  if (loading) return <p className="text-ink-muted">Loading the covering analysis…</p>
  // Nieudana analiza nie jest ostrzezeniem o dachu, wiec zostaje wyciszona, a nie czerwona.
  if (error) return <p data-testid="analysis-error" className="text-ink-muted">{error}</p>
  if (analysis === null) return null

  const mock = analysis.source === 'mock'

  return (
    <div data-testid="roof-analysis" data-source={analysis.source} data-verdict={analysis.verdict}>
      <SourceNote source={analysis.source} />

      {/* Werdykt slownie jest glowna trescia sekcji; first:mt-0 dotyczy wariantu bez mikropodpisu. */}
      <p className="mt-2 flex items-start gap-2 text-ink first:mt-0">
        <span
          data-testid="analysis-dot"
          className={`mt-1.5 inline-block h-2 w-2 shrink-0 ${dotClass(analysis.verdict)}`}
        />
        <span>{VERDICT_TEXT[analysis.verdict]}</span>
      </p>

      <div className="mt-3 border-t border-hairline pt-3">
        <p className="label-micro">Probability</p>
        {analysis.probability === null ? (
          // Zero znaczyloby „model sprawdzil i nie widzi eternitu" — brak wyniku to inna informacja.
          <p className="mt-1 text-ink-muted">No numeric result — no result is not the same as zero.</p>
        ) : (
          <p
            data-testid="analysis-probability"
            className={`font-display mt-0.5 text-2xl leading-none ${mock ? 'text-ink-faint' : 'text-ink'}`}
          >
            {percentLabel(analysis.probability)}
          </p>
        )}
        {mock && analysis.probability !== null ? (
          <p className="mt-1 text-xs text-ink-faint">The number is illustrative — no model produced it.</p>
        ) : null}
      </div>

      <p className="mt-3 text-xs text-ink-faint">{analysis.note}</p>
      {analysis.modelName ? <p className="label-micro mt-1">Model: {analysis.modelName}</p> : null}
    </div>
  )
}
