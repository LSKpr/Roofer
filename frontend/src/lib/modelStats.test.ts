import { expect, it } from 'vitest'
import type { AreaAnalysis, AreaAnalysisStats, SuspectedRoof } from '../api/client'
import { effectiveThreshold, recountStats, selectFlaggedNotListed } from './modelStats'

function aRoof(id: number, probability: number, listed: boolean, areaM2: number): SuspectedRoof {
  return { id, probability, listed, areaM2, geometry: null }
}

/**
 * Szesc ocenionych dachow, recznie policzalnych, plus dwa bez oceny.
 *
 * Dach 303 ma ocene rowna progowi domyslnemu: to on rozstrzyga, czy warunek jest `>=`, czy `>`.
 */
const ROOFS: SuspectedRoof[] = [
  aRoof(301, 0.81, true, 210),
  aRoof(302, 0.72, false, 163),
  aRoof(303, 0.5, false, 120),
  aRoof(304, 0.49, true, 140),
  aRoof(305, 0.31, false, 88),
  aRoof(306, 0.02, false, 96),
]

/**
 * Liczby tak, jak policzylby je backend przy progu 0,5: podejrzane 301, 302 i 303 (ten ostatni
 * dokladnie na progu), z czego zgloszony jest tylko 301. Zgloszony 304 ma ocene ponizej progu.
 */
const BACKEND_STATS: AreaAnalysisStats = {
  analysed: 6,
  noResult: 2,
  suspected: 3,
  suspectedShare: 0.5,
  suspectedNotListed: 2,
  suspectedListed: 1,
  listedNotSuspected: 1,
  suspectedRoofAreaM2: 493,
  threshold: 0.5,
  modelName: '70b702',
}

function anAnalysis(overrides: Partial<AreaAnalysis> = {}): AreaAnalysis {
  return { stats: BACKEND_STATS, buildings: ROOFS, truncated: false, ...overrides }
}

// Najwazniejszy test tego modulu: przy progu z odpowiedzi nasze liczenie musi dac dokladnie to,
// co przyszlo z serwera. Inaczej samo otwarcie panelu zmienialoby liczby bez ruchu suwaka.
it('przy progu domyslnym daje liczniki identyczne z tymi z backendu', () => {
  const analysis = anAnalysis()

  expect(recountStats(analysis, analysis.stats.threshold)).toEqual(analysis.stats)
})

it('przy wyzszym progu zostawia tylko najwyzsze oceny', () => {
  const stats = recountStats(anAnalysis(), 0.75)

  // Powyzej 0,75 jest sam 301 (0,81), zgloszony. Zgloszone bez flagi: 304.
  expect(stats.suspected).toBe(1)
  expect(stats.suspectedListed).toBe(1)
  expect(stats.suspectedNotListed).toBe(0)
  expect(stats.listedNotSuspected).toBe(1)
  expect(stats.suspectedRoofAreaM2).toBe(210)
  expect(stats.suspectedShare).toBe(0.1667)
  expect(stats.threshold).toBe(0.75)
})

it('przy nizszym progu doklada oceny, ktore przy domyslnym byly ponizej', () => {
  const stats = recountStats(anAnalysis(), 0.3)

  // 0,3 lapie 301, 302, 303, 304 i 305 — wsrod nich zgloszone 301 i 304.
  expect(stats.suspected).toBe(5)
  expect(stats.suspectedListed).toBe(2)
  expect(stats.suspectedNotListed).toBe(3)
  expect(stats.listedNotSuspected).toBe(0)
  expect(stats.suspectedRoofAreaM2).toBe(721)
  expect(stats.suspectedShare).toBe(0.8333)
})

// Granica progu. Backend liczy `probability >= threshold`, wiec ocena rowna progowi jest
// podejrzeniem — ten test pada przy zamianie warunku na `>`.
it('ocene rowna progowi liczy jako podejrzenie', () => {
  const onlyBoundary = anAnalysis({
    stats: { ...BACKEND_STATS, analysed: 1, noResult: 0 },
    buildings: [aRoof(401, 0.35, false, 77)],
  })

  const stats = recountStats(onlyBoundary, 0.35)

  expect(stats.suspected).toBe(1)
  expect(stats.suspectedNotListed).toBe(1)
  expect(stats.suspectedRoofAreaM2).toBe(77)
  expect(stats.suspectedShare).toBe(1)
  // Tuz nad granica ten sam dach jest juz poza flaga.
  expect(recountStats(onlyBoundary, 0.36).suspected).toBe(0)
})

it('sumuje powierzchnie dachow tylko dla podejrzanych', () => {
  const wholeArea = ROOFS.reduce((sum, roof) => sum + roof.areaM2, 0)

  expect(recountStats(anAnalysis(), 0.75).suspectedRoofAreaM2).toBe(210)
  expect(recountStats(anAnalysis(), 0.75).suspectedRoofAreaM2).not.toBe(wholeArea)
  expect(recountStats(anAnalysis(), 1.01).suspectedRoofAreaM2).toBe(0)
})

it('zaokragla udzial do czterech cyfr, a powierzchnie do jednej — tak jak backend', () => {
  const thirds = anAnalysis({
    stats: { ...BACKEND_STATS, analysed: 3, noResult: 0 },
    buildings: [aRoof(501, 0.9, false, 120.25), aRoof(502, 0.4, false, 88.14), aRoof(503, 0.1, false, 60.01)],
  })

  expect(recountStats(thirds, 0.5).suspectedShare).toBe(0.3333)
  expect(recountStats(thirds, 0.2).suspectedShare).toBe(0.6667)
  expect(recountStats(thirds, 0.2).suspectedRoofAreaM2).toBe(208.4)
})

it('przy progu 0 flaguje wszystko, co dostalo ocene', () => {
  const stats = recountStats(anAnalysis(), 0)

  expect(stats.suspected).toBe(6)
  expect(stats.suspectedListed).toBe(2)
  expect(stats.suspectedNotListed).toBe(4)
  expect(stats.listedNotSuspected).toBe(0)
  expect(stats.suspectedRoofAreaM2).toBe(817)
  expect(stats.suspectedShare).toBe(1)
  // Prog 0 nie zamienia dachow bez oceny w ocenione.
  expect(stats.analysed).toBe(6)
  expect(stats.noResult).toBe(2)
})

it('przy progu 1 zostaje tylko pewna ocena', () => {
  const stats = recountStats(anAnalysis(), 1)

  expect(stats.suspected).toBe(0)
  expect(stats.suspectedNotListed).toBe(0)
  expect(stats.suspectedRoofAreaM2).toBe(0)
  expect(stats.suspectedShare).toBe(0)
  // Wszystkie zgloszone oceniono ponizej progu, wiec oba wchodza do „zgloszonych bez flagi".
  expect(stats.listedNotSuspected).toBe(2)

  const certain = anAnalysis({
    stats: { ...BACKEND_STATS, analysed: 1, noResult: 0 },
    buildings: [aRoof(601, 1, false, 50)],
  })
  expect(recountStats(certain, 1).suspected).toBe(1)
})

// Prog przesuwa granice podejrzenia, a nie liczbe zdjec, ktore model obejrzal.
it('nie rusza liczby ocenionych, braku ocen ani nazwy modelu', () => {
  for (const threshold of [0, 0.25, 0.5, 0.9, 1]) {
    const stats = recountStats(anAnalysis(), threshold)

    expect(stats.analysed).toBe(6)
    expect(stats.noResult).toBe(2)
    expect(stats.modelName).toBe('70b702')
  }
})

// Backend oddaje jeszcze `unknownToUs` (budynki ocenione, ktorych nie ma w naszej bazie); typ we
// froncie tego pola nie deklaruje, ale prog go nie dotyczy, wiec musi przejsc nietkniete.
it('przepuszcza pola odpowiedzi, na ktore prog nie ma wplywu', () => {
  type StatsWithUnknown = AreaAnalysisStats & { unknownToUs: number }
  const fromBackend: StatsWithUnknown = { ...BACKEND_STATS, unknownToUs: 2 }

  const stats = recountStats(anAnalysis({ stats: fromBackend }), 0.9) as StatsWithUnknown

  expect(stats.unknownToUs).toBe(2)
})

// Dach bez oceny jest nieznany, a nie czysty: doliczenie go do mianownika zanizaloby udzial
// akurat tam, gdzie zdjecie bylo najgorsze.
it('liczy udzial wzgledem ocenionych, nigdy wzgledem ocenionych razem z brakami', () => {
  const stats = recountStats(anAnalysis(), 0.5)

  expect(stats.suspectedShare).toBe(0.5)
  expect(stats.suspectedShare).not.toBe(3 / 8)
})

it('pusta lista ocen daje udzial 0, a nie NaN', () => {
  const nothing = anAnalysis({
    stats: { ...BACKEND_STATS, analysed: 0, noResult: 4, suspected: 0, suspectedShare: 0 },
    buildings: [],
  })

  const stats = recountStats(nothing, 0.5)

  expect(stats.suspectedShare).toBe(0)
  expect(stats.suspected).toBe(0)
})

// Przy przycietej liscie przeliczenie opisywaloby tylko te dachy, ktore przyszly, a etykiety
// obiecuja caly obszar — wiec nie przeliczamy wcale.
it('przy przycietej liscie oddaje liczby backendu i jego prog', () => {
  const truncated = anAnalysis({ truncated: true })

  expect(recountStats(truncated, 0.9)).toEqual(BACKEND_STATS)
  expect(recountStats(truncated, 0.9).threshold).toBe(0.5)
  expect(recountStats(truncated, 0).suspected).toBe(3)
})

it('obowiazujacy prog to wybor uzytkownika, a bez wyboru prog z odpowiedzi', () => {
  expect(effectiveThreshold(anAnalysis(), null)).toBe(0.5)
  expect(effectiveThreshold(anAnalysis(), 0.85)).toBe(0.85)
  // Tam, gdzie nie przeliczamy, obowiazuje prog, ktorym policzone sa widoczne liczby.
  expect(effectiveThreshold(anAnalysis({ truncated: true }), 0.85)).toBe(0.5)
})

/** Same identyfikatory: w tym wyborze liczy sie to, ktore dachy weszly i w jakiej kolejnosci. */
function pickedIds(analysis: AreaAnalysis, threshold: number): number[] {
  return selectFlaggedNotListed(analysis, threshold).map((roof) => roof.id)
}

// Najwazniejszy warunek tej listy: zgloszony dach nie ma prawa sie na niej znalezc, nawet z
// najwyzsza ocena. Lista, ktora pokazuje zgloszone budynki jako niezgloszone, jest gorsza niz brak
// listy — ten test pada przy usunieciu warunku `!listed`.
it('bierze tylko dachy poza rejestrem i tylko od progu w gore', () => {
  // 301 ma najwyzsza ocene (0,81), ale jest zgloszony. 305 i 306 sa ponizej progu.
  expect(pickedIds(anAnalysis(), 0.5)).toEqual([302, 303])
})

it('ustawia najwyzsza ocene na gorze, bo to pierwszy dach do obejrzenia', () => {
  expect(pickedIds(anAnalysis(), 0)).toEqual([302, 303, 305, 306])
})

// Ta sama granica, ktorej pilnuje `recountStats`: ocena rowna progowi jest podejrzeniem.
it('ocene rowna progowi wpuszcza na liste', () => {
  expect(pickedIds(anAnalysis(), 0.5)).toContain(303)
  expect(pickedIds(anAnalysis(), 0.51)).not.toContain(303)
})

// Lista i liczba prowadzaca musza pochodzic z tego samego progu, bo inaczej naglowek obiecuje
// inna liczbe dachow, niz da sie policzyc wierszami.
it('ma tyle pozycji, ile wynosi suspectedNotListed przy tym samym progu', () => {
  for (const threshold of [0, 0.3, 0.5, 0.75, 1]) {
    const analysis = anAnalysis()

    expect(selectFlaggedNotListed(analysis, threshold)).toHaveLength(
      recountStats(analysis, threshold).suspectedNotListed,
    )
  }
})

it('przy progu nad wszystkimi ocenami oddaje pusta liste, a nie cala', () => {
  expect(selectFlaggedNotListed(anAnalysis(), 1.01)).toEqual([])
})

// Sortowanie w miejscu na `analysis.buildings` przestawialoby dachy tez na mapie, ktora czyta
// te sama tablice.
it('nie przestawia dachow w odpowiedzi modelu', () => {
  const analysis = anAnalysis()

  selectFlaggedNotListed(analysis, 0)

  expect(analysis.buildings.map((roof) => roof.id)).toEqual([301, 302, 303, 304, 305, 306])
})

it('przy rownych ocenach zostawia kolejnosc z odpowiedzi', () => {
  const sameScore = anAnalysis({
    buildings: [aRoof(701, 0.6, false, 90), aRoof(702, 0.6, false, 300), aRoof(703, 0.9, false, 70)],
  })

  expect(pickedIds(sameScore, 0.5)).toEqual([703, 701, 702])
})

// Przy przycietej odpowiedzi liczby sa backendowe, a tu sa tylko te dachy, ktore przyszly —
// panel przyznaje sie do tego zdaniem pod lista.
it('przy przycietej odpowiedzi opisuje tylko dachy, ktore przyszly', () => {
  const truncated = anAnalysis({ stats: { ...BACKEND_STATS, suspectedNotListed: 120 }, truncated: true })

  // Liczby zostaja backendowe (120 w calym obszarze), a lista zna tylko oceny, ktore przyszly.
  expect(pickedIds(truncated, truncated.stats.threshold)).toEqual([302, 303])
  expect(recountStats(truncated, truncated.stats.threshold).suspectedNotListed).toBe(120)
})
