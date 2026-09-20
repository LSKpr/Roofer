import { useState, type KeyboardEvent } from 'react'
import { usePlaceSearch, MIN_QUERY_LENGTH } from '../hooks/usePlaceSearch'
import type { Place } from '../api/client'

type SearchBoxProps = {
  onPick: (place: Place) => void
  className?: string
}

const LISTBOX_ID = 'search-box-places'

function optionId(index: number): string {
  return `${LISTBOX_ID}-option-${index}`
}

/**
 * Nominatim zwraca caly adres administracyjny w jednym polu
 * („Zwoleń, gmina Zwoleń, …, województwo mazowieckie, 26-700, Polska"). Pierwszy segment to
 * nazwa miejsca i tylko on jest czytany wzrokiem, reszta jest kontekstem — dlatego ida osobno.
 */
function splitLabel(label: string): { name: string; context: string } {
  const comma = label.indexOf(',')
  if (comma === -1) return { name: label.trim(), context: '' }
  return { name: label.slice(0, comma).trim(), context: label.slice(comma + 1).trim() }
}

/**
 * Pole wyszukiwania miejscowosci z podpowiedziami.
 *
 * Jedyny komponent, ktory sam pobiera dane — reszta interfejsu dostaje wszystko propsami.
 * Rodzic odpowiada za pozycjonowanie calosci; `absolute` jest tu tylko na liscie podpowiedzi
 * wzgledem wlasnego opakowania, zeby nie przepychala mapy w dol.
 */
export function SearchBox({ onPick, className }: SearchBoxProps) {
  const { query, setQuery, results, loading, error, clear } = usePlaceSearch()
  // Zaznaczenie klawiatura to jedyny stan, ktorego hook nie zna: dotyczy widoku, nie danych.
  const [active, setActive] = useState(-1)
  const [collapsed, setCollapsed] = useState(false)

  const asks = query.trim().length >= MIN_QUERY_LENGTH
  const open = asks && !collapsed
  // aria-expanded i aria-controls opisuja liste, a nie sam panel: przy „Searching…" i bledzie
  // zadnego listboxa w drzewie nie ma, wiec czytnik nie ma czego ogloszic jako rozwiniete.
  const listVisible = open && error === null && !loading && results.length > 0

  function pick(place: Place) {
    // Fraza zostaje ta, ktora wpisal uzytkownik: wstawienie dlugiego label-a odpaliloby
    // kolejne zapytanie do wyszukiwarki, a ta ma limit jednego na sekunde.
    setCollapsed(true)
    setActive(-1)
    onPick(place)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      setCollapsed(true)
      setActive(-1)
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (results.length === 0) return
      event.preventDefault()
      setCollapsed(false)
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((previous) => {
        // Bez zaznaczenia strzalka w dol wchodzi na pierwsza pozycje, a w gore na ostatnia.
        // Liczenie modulo od -1 dawaloby tu druga od konca, czyli pozycje wzieta z niczego.
        if (previous < 0) return step === 1 ? 0 : results.length - 1
        return (previous + step + results.length) % results.length
      })
      return
    }
    if (event.key === 'Enter') {
      if (!open || results.length === 0) return
      event.preventDefault()
      // Bez zaznaczenia Enter bierze pierwsza podpowiedz — inaczej nic by nie robil.
      pick(results[active >= 0 ? active : 0])
    }
  }

  return (
    <div className={className ? `relative ${className}` : 'relative'}>
      <div className="relative">
        <input
          type="search"
          role="combobox"
          aria-label="Search for a place or address"
          aria-expanded={listVisible}
          aria-controls={listVisible ? LISTBOX_ID : undefined}
          aria-autocomplete="list"
          aria-activedescendant={listVisible && active >= 0 ? optionId(active) : undefined}
          placeholder="Search for a place or address"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setCollapsed(false)
            setActive(-1)
          }}
          onKeyDown={handleKeyDown}
          // Krzyzyk czyszczacy jest wlasny, wiec natywny z WebKita byloby drugim takim samym.
          className="w-full border-b border-hairline bg-surface py-2.5 pr-9 pl-3 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none [&::-webkit-search-cancel-button]:appearance-none"
        />
        {query === '' ? null : (
          <button
            type="button"
            aria-label="Clear"
            onClick={() => {
              clear()
              setActive(-1)
              setCollapsed(false)
            }}
            className="absolute top-1/2 right-1 -translate-y-1/2 px-2 py-1 text-sm leading-none text-ink-faint hover:text-ink"
          >
            ×
          </button>
        )}
      </div>

      {open ? (
        <div className="absolute inset-x-0 top-full z-10 rounded-card border border-hairline bg-surface shadow-[0_1px_3px_rgba(5,28,44,0.08)]">
          {error ? (
            <div className="px-3 py-2.5">
              <p className="label-micro">Error</p>
              <p className="mt-0.5 text-xs text-ink">{error}</p>
            </div>
          ) : loading ? (
            <p className="label-micro px-3 py-2.5">Searching…</p>
          ) : results.length === 0 ? (
            <p className="px-3 py-2.5 text-xs text-ink-muted">No results</p>
          ) : (
            <ul role="listbox" id={LISTBOX_ID} aria-label="Place suggestions" className="divide-y divide-hairline">
              {results.map((place, index) => {
                const { name, context } = splitLabel(place.label)
                return (
                  <li
                    key={`${place.label}-${place.lat}-${place.lng}`}
                    id={optionId(index)}
                    role="option"
                    aria-selected={index === active}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => pick(place)}
                    className={`cursor-pointer px-3 py-2.5 ${index === active ? 'bg-surface-muted' : 'bg-surface'}`}
                  >
                    <span className="block text-sm leading-snug text-ink">{name}</span>
                    {context ? <span className="mt-0.5 block text-xs leading-snug text-ink-muted">{context}</span> : null}
                    {place.kind ? <span className="label-micro mt-1 block">{place.kind}</span> : null}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}
