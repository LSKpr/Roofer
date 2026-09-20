import { useId } from 'react'
import { ScoreHistogram } from './ScoreHistogram'

type ThresholdSliderProps = {
  /** Prog podejrzenia jako ulamek 0–1, tak jak `threshold` w odpowiedzi modelu. */
  value: number
  onChange: (value: number) => void
  /** Prog, przy ktorym liczy backend i przy ktorym zmierzono skutecznosc modelu. */
  modelDefault: number
  /**
   * Oceny wszystkich OCENIONYCH dachow obszaru (`probability` z `analysis.buildings`) — z nich
   * rysuje sie rozklad pod torem suwaka. Pusta tablica jest normalnym stanem (wynik bez ani jednej
   * oceny) i wtedy wykresu po prostu nie ma.
   */
  scores: number[]
  className?: string
}

/** Krok 5 punktow procentowych: drobniej niz to nie da sie odczytac z liczb w panelu. */
const STEP = 0.05

function percentLabel(value: number): string {
  return `${Math.round(value * 100)}%`
}

/** Prog z suwaka jest ulamkiem dziesietnym w double, wiec porownujemy z tolerancja, nie na rowno. */
function isModelDefault(value: number, modelDefault: number): boolean {
  return Math.abs(value - modelDefault) < 1e-9
}

/**
 * Suwak progu podejrzenia. Czysto prezentacyjny, jak `RegistryToggle`: stan trzyma `App`, bo ten
 * sam prog liczy liczby w panelu i filtruje pomaranczowe obrysy na mapie.
 *
 * Prawdziwy `<input type="range">`, a nie wlasny uchwyt z diva: strzalki, Home/End, Page Up/Down,
 * tabulacja i komunikat czytnika ekranu przychodza wtedy z przegladarki, zamiast byc odtwarzane
 * recznie i gorzej.
 *
 * Podpisy obu koncow stoja pod suwakiem, a nie w pomocy kontekstowej: prog jest kompromisem
 * miedzy falszywym alarmem a przeoczeniem i uzytkownik musi ten kompromis widziec, zanim ruszy
 * uchwytem — sama liczba „35%" nie mowi, w ktora strone jest ostrozniej.
 *
 * Pod torem stoi rozklad ocen (`ScoreHistogram`) i dlatego ten suwak dostaje oceny, mimo ze sam
 * nic z nimi nie liczy: histogram musi miec DOKLADNIE ta sama szerokosc co pole, zeby os 0-1
 * pokrywala tor suwaka. Gdyby wykres siedzial w panelu obok suwaka, kazdy odstep rozjechalby obie
 * osie. Podpisy koncow zostaja pod wykresem, bo opisuja te sama os.
 */
export function ThresholdSlider({ value, onChange, modelDefault, scores, className }: ThresholdSliderProps) {
  // Identyfikator z Reacta, a nie stala: dwa takie suwaki na jednym ekranie mialyby ten sam
  // `id` i etykieta klikalaby w cudze pole.
  const inputId = useId()

  return (
    <div className={className ?? ''}>
      <div className="flex items-baseline justify-between gap-4">
        <label htmlFor={inputId} className="label-micro">
          Suspicion threshold
        </label>
        {/* Prog czyta sie jako procent, bo tak samo podany jest udzial dachow z flaga. */}
        <span data-testid="threshold-value" className="font-display text-base leading-none text-ink">
          {percentLabel(value)}
        </span>
      </div>

      <input
        id={inputId}
        type="range"
        min={0}
        max={1}
        step={STEP}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-label="Suspicion threshold"
        // `accent-suspected` to token --color-suspected, ten sam, ktorym mapa maluje obrysy;
        // reszta zostaje natywna, bo wlasny uchwyt z diva odebralby polu obsluge klawiatury.
        className="mt-2 w-full cursor-pointer accent-suspected focus-visible:outline-1 focus-visible:outline-accent"
      />

      {/* Rozklad ocen tuz pod torem, bez niczego pomiedzy: dopiero styk obu elementow pozwala
          czytac slupki i uchwyt w jednej osi. Przy braku ocen komponent nie rysuje nic. */}
      <ScoreHistogram scores={scores} threshold={value} className="mt-1.5" />

      {/* Istota tej decyzji: w obie strony sie cos traci, tylko co innego. */}
      <div className="mt-1 flex items-start justify-between gap-4 text-[10px] leading-tight text-ink-faint">
        <span>Fewer flags, more missed</span>
        <span className="text-right">More flags, more false alarms</span>
      </div>

      {/* Wlasne ustawienie nie moze wygladac jak wynik modelu, wiec prog modelu stoi obok niego. */}
      {isModelDefault(value, modelDefault) ? null : (
        <p className="mt-1.5 text-xs text-ink-muted">Model default: {percentLabel(modelDefault)}</p>
      )}
    </div>
  )
}
