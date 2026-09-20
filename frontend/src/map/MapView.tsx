import { Map as MapLibreMap, NavigationControl, ScaleControl } from 'maplibre-gl'
import type { GeoJSONSource } from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import type { Bounds } from '../api/client'
import { attachRectangleDraw, rectanglePolygon, type RectangleDraw } from './rectangleDraw'
import type { BasemapId } from './basemap'
import { BASEMAPS, DEFAULT_BASEMAP, INITIAL_CENTER, INITIAL_ZOOM, MAX_ZOOM, MIN_ZOOM } from './basemap'
import {
  CLICKABLE_LAYER_IDS,
  HIGHLIGHT_LAYER_IDS,
  LAYER_IDS,
  MAP_LAYERS,
  SCAN_AREA_LAYERS,
  SCAN_AREA_SOURCE_ID,
  SOURCE_ID,
  SUSPECTED_LAYERS,
  SUSPECTED_SOURCE_ID,
  buildingsSource,
  fillColor,
  fillOpacity,
  lineWidth,
  outlineColor,
  selectedFilter,
  suspectedRoofsCollection,
} from './layers'
import type { SuspectedRoof } from './layers'

/** Kontrakt z backendem i z `App.tsx` mieszka w layers.ts; tutaj tylko go przepuszczamy dalej. */
export type { SuspectedRoof } from './layers'

/**
 * Cel kamery. Wyszukiwarka oddaje albo prostokat miejscowosci, albo sam punkt (adres, przysiolek),
 * wiec mapa musi umiec jedno i drugie. Kolejnosc w `bounds` to [zachod, poludnie, wschod, polnoc].
 */
export type MapFocus =
  | { kind: 'bounds'; bounds: [number, number, number, number] }
  | { kind: 'point'; center: [number, number]; zoom: number }

export type MapViewProps = {
  /** Identyfikator budynku do podswietlenia; `null` znaczy „nic nie wybrano". */
  selectedId?: number | null
  onSelect?: (id: number | null) => void
  /** Aktualny zoom po kazdym przesunieciu — na komunikat „przybliz, aby zobaczyc obrysy". */
  onZoomChange?: (zoom: number) => void
  /** Podklad mapy. Zmiana podmienia sam styl, mapa i warstwy budynkow zostaja. */
  basemap?: BasemapId
  /** Kazdy nowy obiekt przesuwa kamere; `null` nie robi nic. */
  focus?: MapFocus | null
  /** Tryb rysowania prostokata do skanu. Wylacza przeciaganie mapy, dopoki trwa. */
  drawing?: boolean
  onDrawComplete?: (bounds: Bounds) => void
  onDrawCancel?: () => void
  /**
   * Obszar, ktorego dotyczy aktualny wynik skanu. Rysuje sie na mapie tak dlugo, jak dlugo rodzic
   * go trzyma — takze wtedy, gdy panel wyniku ustapil karcie budynku albo gdy skan skonczyl sie
   * bledem. `null` znaczy „nie ma czego pokazywac" i usuwa prostokat z mapy.
   */
  scannedArea?: Bounds | null
  /**
   * Czy mapa ma podswietlac budynki zgloszone w rejestrze. Domyslnie tak — wylaczenie zdejmuje
   * czerwien i chowa cieplo, ale nie rusza samych warstw budynkow (patrz `applyRegistry`).
   */
  showRegistry?: boolean
  /**
   * Budynki, na ktorych model widzi pokrycie typu eternit. Mapa rysuje dokladnie to, co dostanie:
   * progowanie po `probability` nalezy do rodzica, bo prog jest decyzja interfejsu, a nie mapy.
   * `null` znaczy „nie ma czego pokazywac" i zdejmuje warstwe; pusta lista zostawia ja bez obiektow.
   */
  suspectedRoofs?: SuspectedRoof[] | null
}

/** Filtr ustawiamy tylko na warstwach, ktore juz istnieja — powstaja dopiero po `style.load`. */
function applyHighlight(instance: MapLibreMap, id: number | null) {
  const filter = selectedFilter(id)
  for (const layerId of HIGHLIGHT_LAYER_IDS) {
    if (instance.getLayer(layerId)) instance.setFilter(layerId, filter)
  }
}

/**
 * `style.load` leci po kazdym `setStyle`, a MapLibre razem ze starym stylem usuwa zrodla i warstwy
 * dodane recznie. Dlatego dokladanie musi byc odporne na powtorzenie: sprawdzamy, czego brakuje,
 * zamiast zakladac czysta mape.
 */
function addBuildingLayers(instance: MapLibreMap) {
  if (!instance.getSource(SOURCE_ID)) instance.addSource(SOURCE_ID, buildingsSource)
  for (const layer of MAP_LAYERS) {
    if (!instance.getLayer(layer.id)) instance.addLayer(layer)
  }
}

/**
 * Przelacznik rejestru zmienia KOLOR, a nie widocznosc warstwy wypelnienia: `LAYER_IDS.fill` jest
 * jedynym celem klikniec (`CLICKABLE_LAYER_IDS`), wiec ukrycie go zabraloby mozliwosc otwarcia
 * karty budynku. Chowamy za to heatmape — niesie te sama informacje z rejestru, tylko na innym
 * zoomie, wiec zostawienie jej byloby niekonsekwencja.
 *
 * Jak wszystko dodane recznie, wywolanie musi byc odporne na powtorzenie: po `setStyle` warstwy
 * powstaja od nowa w stanie domyslnym i stan przelacznika trzeba nalozyc jeszcze raz.
 */
function applyRegistry(instance: MapLibreMap, show: boolean) {
  if (instance.getLayer(LAYER_IDS.fill)) {
    instance.setPaintProperty(LAYER_IDS.fill, 'fill-color', fillColor(show))
    // Samo zdjecie czerwieni nie wystarcza: zgloszony budynek kryty 0,62 wobec 0,22 sasiada
    // bylby nadal oznaczony, tylko innym srodkiem. Przelacznik ma zdejmowac oznaczenie.
    instance.setPaintProperty(LAYER_IDS.fill, 'fill-opacity', fillOpacity(show))
  }
  if (instance.getLayer(LAYER_IDS.outline)) {
    instance.setPaintProperty(LAYER_IDS.outline, 'line-color', outlineColor(show))
    instance.setPaintProperty(LAYER_IDS.outline, 'line-width', lineWidth(show))
  }
  if (instance.getLayer(LAYER_IDS.density)) {
    instance.setLayoutProperty(LAYER_IDS.density, 'visibility', show ? 'visible' : 'none')
  }
}

/**
 * Prostokat zeskanowanego obszaru. Geometrie liczy `rectanglePolygon` z rectangleDraw.ts — ten sam
 * pierscien, ktory widzi uzytkownik w trakcie przeciagania, wiec zaznaczenie i wynik nie moga sie
 * rozjechac o piksel. Brak obszaru zdejmuje warstwy razem ze zrodlem, zamiast zostawiac je puste:
 * pusta warstwa nadal odpowiadalaby na zapytania o styl i mieszala w kolejnosci rysowania.
 *
 * Wywolanie musi byc odporne na powtorzenie z tego samego powodu co warstwy budynkow: po `setStyle`
 * mapa jest pusta i wszystko trzeba dolozyc od nowa.
 */
function applyScannedArea(instance: MapLibreMap, area: Bounds | null) {
  if (!area) {
    // Najpierw warstwy, potem zrodlo: MapLibre nie usunie zrodla, z ktorego ktos jeszcze czyta.
    for (const layer of SCAN_AREA_LAYERS) {
      if (instance.getLayer(layer.id)) instance.removeLayer(layer.id)
    }
    if (instance.getSource(SCAN_AREA_SOURCE_ID)) instance.removeSource(SCAN_AREA_SOURCE_ID)
    return
  }
  const data = rectanglePolygon(area)
  const source = instance.getSource<GeoJSONSource>(SCAN_AREA_SOURCE_ID)
  // Istniejacemu zrodlu podmieniamy dane: usuwanie i dodawanie go przy kazdym nowym skanie
  // zabieraloby ze soba warstwy i mrugaloby prostokatem.
  if (source) source.setData(data)
  else instance.addSource(SCAN_AREA_SOURCE_ID, { type: 'geojson', data })
  for (const layer of SCAN_AREA_LAYERS) {
    if (!instance.getLayer(layer.id)) instance.addLayer(layer)
  }
}

/**
 * Obrysy budynkow, na ktorych model widzi eternit. Warstwa wchodzi PRZED podswietleniem wyboru,
 * a wiec nad budynkami i pod wybranym budynkiem: pomaranczowy obrys ma byc widoczny razem
 * z kolorem rejestru pod spodem, ale nie moze przykrywac tego, co uzytkownik wlasnie kliknal.
 *
 * Wywolanie jest odporne na powtorzenie z tego samego powodu co przy prostokacie skanu: po
 * `setStyle` mapa jest pusta i wszystko trzeba dolozyc od nowa.
 */
function applySuspectedRoofs(instance: MapLibreMap, roofs: SuspectedRoof[] | null) {
  if (!roofs) {
    // Najpierw warstwy, potem zrodlo: MapLibre nie usunie zrodla, z ktorego ktos jeszcze czyta.
    for (const layer of SUSPECTED_LAYERS) {
      if (instance.getLayer(layer.id)) instance.removeLayer(layer.id)
    }
    if (instance.getSource(SUSPECTED_SOURCE_ID)) instance.removeSource(SUSPECTED_SOURCE_ID)
    return
  }
  const data = suspectedRoofsCollection(roofs)
  const source = instance.getSource<GeoJSONSource>(SUSPECTED_SOURCE_ID)
  // Istniejacemu zrodlu podmieniamy dane: usuwanie go przy kazdym nowym wyniku zabieraloby
  // ze soba warstwe i mrugaloby obrysami.
  if (source) source.setData(data)
  else instance.addSource(SUSPECTED_SOURCE_ID, { type: 'geojson', data })
  // Miejsce w stosie okresla `beforeId`, a nie moment wywolania. Gdy podswietlenia jeszcze nie ma
  // (MapLibre rzuca na nieistniejacym `beforeId`), warstwa wyladuje na wierzchu i wroci na swoje
  // miejsce przy najblizszym `style.load`, ktory doklada wszystko w komplecie.
  const before = HIGHLIGHT_LAYER_IDS.find((layerId) => instance.getLayer(layerId))
  for (const layer of SUSPECTED_LAYERS) {
    if (!instance.getLayer(layer.id)) instance.addLayer(layer, before)
  }
}

export function MapView({
  selectedId = null,
  onSelect,
  onZoomChange,
  basemap = DEFAULT_BASEMAP,
  focus = null,
  drawing = false,
  onDrawComplete,
  onDrawCancel,
  scannedArea = null,
  showRegistry = true,
  suspectedRoofs = null,
}: MapViewProps) {
  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<MapLibreMap | null>(null)
  // Mapa powstaje raz, wiec handlery musza czytac propsy z refow. Inaczej zamknelyby sie
  // na wartosciach z pierwszego renderu albo wymusilyby przebudowe mapy przy kazdym renderze.
  const selectRef = useRef(onSelect)
  const zoomRef = useRef(onZoomChange)
  const selectedRef = useRef(selectedId)
  const drawCompleteRef = useRef(onDrawComplete)
  const drawCancelRef = useRef(onDrawCancel)
  const scannedAreaRef = useRef(scannedArea)
  const showRegistryRef = useRef(showRegistry)
  const suspectedRoofsRef = useRef(suspectedRoofs)
  const draw = useRef<RectangleDraw | null>(null)
  const styleReady = useRef(false)
  // Styl, ktory mapa juz dostala. Pierwszy dostaje przez konstruktor, wiec `setStyle` na starcie
  // byloby drugim, niepotrzebnym zaladowaniem tych samych kafli.
  const appliedBasemap = useRef(basemap)
  const hoverBound = useRef(false)

  useEffect(() => {
    selectRef.current = onSelect
    zoomRef.current = onZoomChange
    selectedRef.current = selectedId
    drawCompleteRef.current = onDrawComplete
    drawCancelRef.current = onDrawCancel
    scannedAreaRef.current = scannedArea
    showRegistryRef.current = showRegistry
    suspectedRoofsRef.current = suspectedRoofs
  })

  useEffect(() => {
    if (!container.current || map.current) return
    const instance = new MapLibreMap({
      container: container.current,
      style: BASEMAPS[appliedBasemap.current].style,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
    })
    // Oba w prawym dolnym rogu: gorny prawy zajmuje karta budynku, a dolny lewy legenda.
    instance.addControl(new NavigationControl(), 'bottom-right')
    instance.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-right')

    instance.on('style.load', () => {
      styleReady.current = true
      addBuildingLayers(instance)
      // Warstwy wracaja w stanie domyslnym (podswietlenie wlaczone), wiec wylaczony przelacznik
      // trzeba nalozyc od nowa — inaczej zmiana podkladu po cichu przywracalaby czerwien.
      applyRegistry(instance, showRegistryRef.current)
      // Wybor moze pochodzic z czasu przed zaladowaniem stylu (np. z adresu URL) albo przetrwac
      // zmiane podkladu, ktora zabrala warstwy podswietlenia razem ze starym stylem.
      applyHighlight(instance, selectedRef.current)
      // Po warstwach budynkow, zeby prostokat zostal nad obrysami. Wynik skanu nie znika przez
      // to, ze uzytkownik przelaczyl podklad, wiec jego obszar tez ma wrocic na mape.
      applyScannedArea(instance, scannedAreaRef.current)
      // Wynik modelu przezywa zmiane podkladu tak samo jak wynik skanu, a o miejsce w stosie
      // dba `beforeId` — dlatego wolno go dolozyc na koncu, po podswietleniu.
      applySuspectedRoofs(instance, suspectedRoofsRef.current)

      // Handlery kursora zostaja przy mapie, nie przy stylu, wiec rejestrujemy je tylko raz —
      // po drugim `style.load` mielibysmy inaczej dwa zestawy tych samych nasluchow.
      if (!hoverBound.current) {
        hoverBound.current = true
        for (const layerId of CLICKABLE_LAYER_IDS) {
          instance.on('mouseenter', layerId, () => {
            instance.getCanvas().style.cursor = 'pointer'
          })
          instance.on('mouseleave', layerId, () => {
            instance.getCanvas().style.cursor = ''
          })
        }
      }

      zoomRef.current?.(instance.getZoom())
    })

    // Jeden handler na cala mape zamiast osobnych na warstwach: klik w obrys i klik w pustke
    // to ta sama decyzja, a przy dwoch handlerach kazdy klik w budynek wolalby onSelect dwa razy.
    instance.on('click', (event) => {
      const layers = CLICKABLE_LAYER_IDS.filter((layerId) => instance.getLayer(layerId))
      const features = layers.length > 0 ? instance.queryRenderedFeatures(event.point, { layers }) : []
      const hit = features.find((feature) => feature.id !== undefined && feature.id !== null)
      selectRef.current?.(hit ? Number(hit.id) : null)
    })

    instance.on('zoomend', () => {
      zoomRef.current?.(instance.getZoom())
    })

    // Rysowanie dokłada swoje warstwy dopiero przy `start()`, wiec wolno je doczepic przed
    // zaladowaniem stylu.
    draw.current = attachRectangleDraw(instance, {
      onComplete: (bounds) => drawCompleteRef.current?.(bounds),
      onCancel: () => drawCancelRef.current?.(),
    })

    map.current = instance
    return () => {
      draw.current?.destroy()
      draw.current = null
      instance.remove()
      styleReady.current = false
      hoverBound.current = false
      map.current = null
    }
  }, [])

  /**
   * Podmieniamy sam styl, zeby nie tracic instancji mapy, kamery ani nasluchow. `diff: false`
   * jest tu konieczne: przy domyslnym diffie MapLibre porownuje nowy styl z aktualnym, w ktorym
   * siedza nasze recznie dodane warstwy budynkow — usunalby je jako „nadmiarowe" i nie wyslalby
   * `style.load`, wiec nie mielibysmy momentu, w ktorym je odtworzyc.
   */
  useEffect(() => {
    const instance = map.current
    if (!instance || appliedBasemap.current === basemap) return
    appliedBasemap.current = basemap
    styleReady.current = false
    instance.setStyle(BASEMAPS[basemap].style, { diff: false })
  }, [basemap])

  /**
   * `maxZoom` przy prostokacie miejscowosci: bez tego `fitBounds` na malej wsi wjezdza na zoom 18,
   * gdzie widac trzy budynki. `POLYGON_MIN_ZOOM` z layers.ts to progi obrysow, wiec dolny limit
   * trzyma nas w zakresie, w ktorym mapa cokolwiek pokazuje.
   */
  useEffect(() => {
    const instance = map.current
    if (!instance || !focus) return
    if (focus.kind === 'bounds') {
      const [west, south, east, north] = focus.bounds
      instance.fitBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: 48, maxZoom: 17, duration: 600 },
      )
      return
    }
    instance.flyTo({ center: focus.center, zoom: focus.zoom, duration: 600 })
  }, [focus])

  /** Tryb rysowania wlacza rodzic propsem; modul sam sie wylacza po zakonczeniu ramki. */
  useEffect(() => {
    const handle = draw.current
    if (!handle) return
    if (drawing && !handle.active) handle.start()
    if (!drawing && handle.active) handle.cancel()
  }, [drawing])

  /**
   * Tak samo jak z podswietleniem wyboru: przed `style.load` nie ma jeszcze warstw, ktorym mozna
   * przestawic kolor, a stan z tego czasu nadrabia handler stylu.
   */
  useEffect(() => {
    const instance = map.current
    if (!instance || !styleReady.current) return
    applyRegistry(instance, showRegistry)
  }, [showRegistry])

  // Przed `style.load` nie ma czego filtrowac — wybor z tego czasu nadrabia sam handler stylu.
  useEffect(() => {
    const instance = map.current
    if (!instance || !styleReady.current) return
    applyHighlight(instance, selectedId)
  }, [selectedId])

  /**
   * Tak samo jak z podswietleniem: przed `style.load` nie ma do czego dokladac warstw, a obszar
   * z tego czasu nadrabia handler stylu. Zycie prostokata jest w calosci decyzja rodzica —
   * tutaj tylko odwzorowujemy prop na mapie.
   */
  useEffect(() => {
    const instance = map.current
    if (!instance || !styleReady.current) return
    applyScannedArea(instance, scannedArea)
  }, [scannedArea])

  /**
   * To samo dla wyniku modelu: mapa odwzorowuje prop, a stan sprzed `style.load` nadrabia handler
   * stylu. Nowa lista podmienia dane w istniejacym zrodle, `null` zdejmuje warstwe z mapy.
   */
  useEffect(() => {
    const instance = map.current
    if (!instance || !styleReady.current) return
    applySuspectedRoofs(instance, suspectedRoofs)
  }, [suspectedRoofs])

  return <div ref={container} data-testid="map" className="h-full w-full" />
}
