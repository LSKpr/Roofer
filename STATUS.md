# STATUS

Stan realizacji faz z `PROJECT.md` §10. Prompty startowe: `PHASES.md`.

| Faza | Zakres | Status | Data | Notatka |
| --- | --- | --- | --- | --- |
| F0 | Fundament monorepo + MySQL | gotowe | 2026-09-20 | `pnpm install/build/typecheck/lint` przechodza po skasowaniu `node_modules`; MySQL 8.4.11 healthy. |
| — | Setup testow (`node:test`) | gotowe | 2026-09-20 | `pnpm test` uruchamia 3 paczki; typecheck i lint obejmuja pliki testowe. |
| F1 | Schema Prisma, OpenAPI, Zod, klient | nie zaczete | — | — |
| F2 | Szkielet backendu i middleware | nie zaczete | — | — |
| F3 | Mock `/bbox` + mapa Leaflet | nie zaczete | — | — |
| F4 | Rysowanie bbox + pobieranie danych | nie zaczete | — | — |
| F5 | Kolorowanie, popupy, legenda | nie zaczete | — | — |
| F6 | Overpass API + cache w MySQL | nie zaczete | — | — |
| F7 | Baza Azbestowa (WMS) | nie zaczete | — | — |
| F8 | Serwis ML (FastAPI + ONNX) | odlozone | — | Decyzja z 2026-09-20: najpierw frontend. |
| F9 | Statystyki, wykres, PDF | nie zaczete | — | — |
| F10 | Dopracowanie + Docker | nie zaczete | — | — |

## Odstepstwa od PROJECT.md

Zatwierdzone przez wlasciciela projektu 2026-09-20:

- **WMS zamiast WFS.** Repo przed przebudowa czytalo status z wektorowego WFS GeoAzbest.
  Wracamy do sondy pikselowej z §7.2. Jest mniej dokladna i nie zwraca atrybutow rekordu.
- **F8 odlozone.** `isPotentiallyAsbestos` zostaje `null` do czasu podpiecia modelu.
  Nigdy `false` dla niesprawdzonego budynku.
- **pnpm 11.27.0, nie 12.x.** pnpm 12 to binarka Rustowa ciagnieta przez `optionalDependencies`,
  ktorych corepack z Node 22 nie instaluje — `corepack pnpm` nie startuje.
- **TypeScript 6.0.3, nie 7.0.2.** TS 7 buduje i typecheckuje poprawnie, ale typescript-eslint 8.70
  odmawia zaladowania przeciw API TS 7, co zostawiloby repo bez lintu.
- **Node 22.14 zamiast 20.** Wersja zainstalowana lokalnie; `engines` dopuszcza `>=20`.
- **Dodany framework testowy.** PROJECT.md §3 zadnego nie wymienia. Wybrane `node:test` (wbudowane)
  plus `tsx`, `jsdom` i `@testing-library/react` do komponentow. Zakres: unit + API + komponenty.

## Dlugi techniczne

- **`packages/database` bez testow.** Bedzie trzymac schemat i reeksport klienta Prismy, wiec nie
  ma tam czystych funkcji do testowania. Dodac dopiero, gdy pojawi sie logika.
- **Testy sa na razie smoke'owe.** Sprawdzaja, ze runner dziala, bo F0 nie ma logiki domenowej.
  Prawdziwe przypadki wchodza od F1.
- **Puste `src/index.ts`** w `database`, `validation` i `backend` — scaffolding F0, wypelnia sie w F1/F2.
- **Stary stack w `legacy/`** (FastAPI + PostGIS + MapLibre) nie jest czescia nowej aplikacji.
  Zostaje, bo narzedzia do wycinania dachow i budowy datasetu nie maja odpowiednika w nowym planie.
- **Sieroce kontenery Dockera** `roofer-web-1`, `roofer-api-1`, `roofer-db-1` ze starego compose
  zajmuja porty 3000/8000/5432. Swiadomie nie ubijane; nowy frontend dev startuje na 3001.
