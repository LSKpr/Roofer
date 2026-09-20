import { useId } from 'react'

type RegistryToggleProps = {
  checked: boolean
  onChange: (value: boolean) => void
  className?: string
}

/**
 * Przelacznik podswietlenia rejestru. Czysto prezentacyjny, jak `BasemapSwitcher`: stan trzyma
 * `App`, bo ta sama wartosc trafia do `MapView` (kolory warstw) i do `Legend` (zdanie o tym,
 * czego na mapie nie widac).
 *
 * Prawdziwy `<input type="checkbox">` z powiazana etykieta, a nie „switch" z diva: klikalna
 * etykieta, spacja, tabulacja i komunikat czytnika ekranu przychodza wtedy z przegladarki,
 * zamiast byc odtwarzane recznie. Kwadrat, nie pigulka — jezyk wizualny nie ma zaokraglen
 * wiekszych niz `rounded-card`.
 */
export function RegistryToggle({ checked, onChange, className }: RegistryToggleProps) {
  // Identyfikator z Reacta, a nie stala: dwa takie przelaczniki na jednym ekranie mialyby
  // ten sam `id` i etykieta klikalaby w cudze pole.
  const inputId = useId()

  return (
    <section
      aria-label="Register highlighting"
      className={`rounded-card border border-hairline bg-surface px-3 py-2 text-ink shadow-[0_1px_3px_rgba(5,28,44,0.08)] ${className ?? ''}`}
    >
      <p className="label-micro">Register</p>
      <div className="mt-1.5 flex items-center gap-2">
        <input
          id={inputId}
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          // `accent-accent` to kolor zaznaczenia z tokenu --color-accent; reszta zostaje natywna,
          // bo wlasny kwadrat z diva odebralby polu obsluge klawiatury.
          className="h-3.5 w-3.5 shrink-0 accent-accent focus-visible:outline-1 focus-visible:outline-accent"
        />
        <label htmlFor={inputId} className="text-xs leading-none text-ink">
          Highlight buildings listed in the register
        </label>
      </div>
    </section>
  )
}
