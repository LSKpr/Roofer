import type { BasemapId } from '../map/basemap'
import { BASEMAPS, BASEMAP_IDS } from '../map/basemap'

type BasemapSwitcherProps = {
  value: BasemapId
  onChange: (id: BasemapId) => void
  className?: string
}

/**
 * Przelacznik podkladu: trzy opcje w jednym rzedzie, rozdzielone wlosowa linia.
 *
 * Komponent jest czysto prezentacyjny — o aktualnym podkladzie decyduje rodzic, bo ten sam stan
 * musi trafic do `MapView` i do stopki z atrybucja. Etykiety i kolejnosc bierzemy z `BASEMAP_IDS`
 * i `BASEMAPS`, zeby dopisanie czwartego podkladu nie wymagalo zmiany tego pliku.
 */
export function BasemapSwitcher({ value, onChange, className }: BasemapSwitcherProps) {
  return (
    <section
      aria-label="Base map"
      className={`rounded-card border border-hairline bg-surface px-3 py-2 text-ink shadow-[0_1px_3px_rgba(5,28,44,0.08)] ${className ?? ''}`}
    >
      <p className="label-micro">Base map</p>
      {/* Ramka i wlosowe linie miedzy przyciskami: rzad ma czytac sie jako jedno pole wyboru. */}
      <div className="mt-1.5 flex divide-x divide-hairline border border-hairline">
        {BASEMAP_IDS.map((id) => {
          const active = id === value
          return (
            <button
              key={id}
              type="button"
              // aria-pressed, bo to przelacznik stanu widoku, a nie odnosnik ani formularz.
              aria-pressed={active}
              onClick={() => onChange(id)}
              className={`flex-1 px-3 py-1.5 text-center text-xs leading-none focus-visible:outline-1 focus-visible:outline-accent ${
                active ? 'bg-ink text-surface' : 'bg-surface text-ink-muted hover:bg-surface-muted hover:text-ink'
              }`}
            >
              {BASEMAPS[id].label}
            </button>
          )
        })}
      </div>
    </section>
  )
}
