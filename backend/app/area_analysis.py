"""Caly zaznaczony prostokat przez model pokrycia dachu: ocena per budynek i szesc licznikow.

Po co ten modul istnieje: `/api/area/scan` mowi, ile budynkow w prostokacie ktos zglosil do
rejestru, a `/api/buildings/{id}/analysis` mowi, co model widzi na jednym dachu. Dopiero
zestawienie obu naraz odpowiada na pytanie, dla ktorego ta aplikacja powstala — **ktorych dachow
nikt nie zglosil, mimo ze wygladaja na pokryte eternitem**. To jest `suspectedNotListed`.

Cztery zasady, ktorych nie wolno tu zlamac:

* **`suspected` znaczy „model widzi pokrycie wygladajace na eternit", nie „jest azbest".** Dlatego
  w statystykach jest `modelName` i `threshold`: da sie powiedziec, co liczylo i od ktorej liczby.
* **Budynek bez oceny nie jest czysty, tylko nieznany.** Statusy inne niz `ok` licza sie do
  `noResult` i nie wchodza do mianownika `suspectedShare` — udzial liczymy wzgledem `analysed`.
  Wliczenie ich do mianownika zanizaloby wynik dokladnie tam, gdzie zdjecie bylo najgorsze.
* **`listed` pochodzi z NASZEJ bazy** (`osm_buildings.registry_matches > 0`), nie od modelu. Model
  nie zna rejestru i nie ma prawa go zgadywac; caly sens tego endpointu polega na tym, ze te dwa
  zrodla sa niezalezne.
* **Bramka limitow stoi po naszej stronie.** Tamta instancja przyjmuje 100 budynkow i 4 km2 na
  zadanie, wiec za duzy prostokat odrzucamy wlasnym 400 z konkretnymi liczbami, zamiast czekac
  kilka sekund na cudze `413 TOO_MANY_BUILDINGS`.

Geometrie budynkow przepuszczamy z odpowiedzi modelu bez przeliczania (patrz `ModelBuilding`),
a `areaM2` i `listed` dokladamy z bazy jednym zapytaniem `WHERE osm_id = ANY(...)` — nie po jednym
zapytaniu na budynek.

Druga polowa tego modulu (`plan_chunks`) odpowiada na pytanie „a co, jesli zaznaczenie jest za
duze": dzieli prostokat na kawalki, z ktorych kazdy przechodzi bramke, zeby front mogl je przepuscic
przez model po kolei. Sam podzial **nie wola modelu** i nie udaje analizy — to tylko lista
prostokatow z licznikiem budynkow.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from math import cos, radians
from typing import Any

from app.area import EARTH_RADIUS_M, BoundingBox, bbox_area_km2, format_km2
from app.prediction import (
    MODEL_MAX_AREA_KM2,
    MODEL_MAX_BUILDINGS,
    SUSPECTED_THRESHOLD,
    AreaModelResult,
)

# Gorna granica listy budynkow w odpowiedzi. Domyslnie rowna limitowi bramki, zeby przy normalnej
# pracy nie dalo sie jej przekroczyc: `truncated` wylacza w panelu suwak progu (nie mamy wtedy
# wszystkich ocen, wiec nie ma z czego przeliczac), a to byloby gorsze niz duza odpowiedz.
# Zostaje jako zabezpieczenie: gdyby usluga oddala wiecej, niz wpuscila nasza bramka, nadwyzke
# zglasza pole `truncated`, tak samo jak w /area/scan.
MAX_ANALYSED_BUILDINGS = MODEL_MAX_BUILDINGS

# Gorna granica liczby kawalkow w planie podzialu. To NIE jest limit modelu, tylko bezpiecznik na
# dwa koszty naraz: zapytania do bazy teraz (najwyzej `2 * MAX_CHUNKS - 1`, czyli 127) i zapytania
# do modelu potem. Drugi z nich decyduje: 64 kawalki po 500 budynkow to 32 000 dachow, czyli od
# ~21 minut (40 ms na dach, sama inferencja) do ~1,6 godziny (0,18 s na dach, gorna granica
# z pomiarow) — a to juz nie jest plan, ktory ktokolwiek wykona. Dlatego `truncated` znaczy tu
# „zmniejsz zaznaczenie", a nie „usterka do obejscia".
#
# Liczba jest potega dwojki nie przez przypadek: kazde ciecie dzieli prostokat na POL, wiec 64
# kawalki to dokladnie szesc poziomow ciecia. Rekurencje ogranicza wiec GLEBOKOSC, a nie licznik
# oddanych kawalkow — dzieki temu obciecie jest rownomierne (kazdy fragment zaznaczenia jest ciety
# tyle samo razy), a nie „zachodnia polowa podzielona, wschodnia urwana", co wyszloby z licznika
# zuzywanego po drodze przez przejscie w glab.
MAX_CHUNKS = 64
MAX_CHUNK_DEPTH = MAX_CHUNKS.bit_length() - 1

_ENVELOPE = "ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)"

# Bramka przed cudzym API: ile budynkow siedzi w prostokacie. Ten sam operator `&&` co w kaflach
# i w skanie obszaru, wiec liczba zgadza sie z tym, co uzytkownik widzi na mapie.
BUILDING_COUNT_SQL = f"""
SELECT count(*)::int AS buildings
FROM osm_buildings b
WHERE b.geom && {_ENVELOPE}
"""

# Fakty z naszej bazy dla budynkow, ktore model odeslal: powierzchnia i to, czy ktos je zglosil.
# Jedno zapytanie na caly obszar. Parametr jest tablica tekstow, bo `osm_buildings.osm_id` jest
# kolumna tekstowa — rzutowanie KOLUMNY na bigint wylaczyloby unikalny indeks z migracji 006.
BUILDING_FACTS_SQL = """
SELECT b.osm_id::bigint                     AS id,
       round(b.area_m2::numeric, 1)::float8 AS area_m2,
       (b.registry_matches > 0)             AS listed
FROM osm_buildings b
WHERE b.osm_id = ANY(%(ids)s)
"""

# Komunikat bramki. Podaje OBA limity i konkretna liczbe, ktora je przebila — „za duzy obszar"
# bez liczb kaze uzytkownikowi zgadywac, o ile ma zmniejszyc prostokat.
LIMIT_MESSAGE = (
    "The model accepts up to {max_buildings:,} buildings and {max_area} km²; this area {actual} "
    "— select a smaller rectangle."
)


@dataclass(frozen=True)
class BuildingFacts:
    """To, co o budynku wie nasza baza — i tylko to. Model dostarcza ocene, baza rejestr."""

    area_m2: float | None
    listed: bool
    """`registry_matches > 0`, czyli „ktos zglosil ten budynek do rejestru". `False` znaczy
    „nie ma go w rejestrze", nigdy „dach jest w porzadku"."""


@dataclass(frozen=True)
class AnalysedBuilding:
    """Budynek z ocena modelu. Bez oceny budynek tu nie trafia — liczy go `no_result`."""

    id: int
    probability: float
    listed: bool
    """Z NASZEJ bazy. Budynek, ktorego baza nie zna, tu nie trafia — patrz `unknown_to_us`."""
    area_m2: float
    geometry: dict[str, Any] | None

    @property
    def suspected(self) -> bool:
        return self.probability >= SUSPECTED_THRESHOLD


@dataclass(frozen=True)
class AreaAnalysisStats:
    """Szesc licznikow, udzial, powierzchnia i dwie liczby, ktore pozwalaja je sprawdzic.

    `suspected_not_listed` jest tu najwazniejsze: budynki, ktorych nikt nie zglosil, a model widzi
    na nich pokrycie wygladajace na eternit. `listed_not_suspected` liczy sie tylko wsrod
    ocenionych — budynek zgloszony, ktorego model nie ocenil, nie jest „modelu zdaniem czysty".
    """

    analysed: int
    no_result: int
    suspected: int
    suspected_share: float
    suspected_not_listed: int
    suspected_listed: int
    listed_not_suspected: int
    suspected_roof_area_m2: float
    threshold: float
    model_name: str
    unknown_to_us: int = 0
    """Budynki ocenione przez model, ktorych nie ma w naszej bazie.

    Nie wchodza do zadnego z licznikow powyzej, bo o ich statusie rejestrowym nic nie wiemy.
    Zaliczenie ich do `suspected_not_listed` bylo by twierdzeniem, ze nikt ich nie zglosil, a my
    wiemy tylko tyle, ze nie ma ich w naszym snapshocie. Przy wspolnym zrodle OSM (2 585 219
    budynkow po obu stronach) powinno tu zawsze stac zero — i wlasnie dlatego ta liczba jest
    widoczna, a nie polkniena: niezerowa znaczy, ze snapshoty sie rozjechaly."""


@dataclass(frozen=True)
class AreaAnalysis:
    stats: AreaAnalysisStats
    buildings: list[AnalysedBuilding]
    truncated: bool


@dataclass(frozen=True)
class AreaChunk:
    """Jeden prostokat, ktory na pewno przejdzie przez bramke `/area/analyze`.

    `buildings` to liczba z bazy policzona tym samym operatorem `&&`, ktorym liczy bramka, wiec
    kawalek z tej listy nie ma prawa dostac 400 „too many buildings" — chyba ze ktos w miedzyczasie
    zmieni limit uslugi albo zaimportuje nowy snapshot.
    """

    bbox: BoundingBox
    buildings: int


@dataclass(frozen=True)
class AreaPlan:
    """Plan podzialu: lista kawalkow plus liczby dotyczace CALEGO prostokata.

    `buildings` jest liczba budynkow w calym zaznaczeniu, a nie suma po kawalkach — te dwie liczby
    nie sa rowne i nie maja byc. Suma po kawalkach jest wieksza albo rowna, bo budynek stojacy na
    granicy dwoch kawalkow wpada do obu (patrz `plan_chunks`).
    """

    chunks: list[AreaChunk]
    buildings: int
    area_km2: float
    truncated: bool


def corners(bbox: BoundingBox) -> tuple[float, float, float, float]:
    """Kolejnosc [west, south, east, north] — ta sama, co `BuildingShape.bbox`."""
    return (bbox.west, bbox.south, bbox.east, bbox.north)


def bbox_parameters(bbox: BoundingBox) -> dict[str, float]:
    return {"south": bbox.south, "west": bbox.west, "north": bbox.north, "east": bbox.east}


def model_limit_problem(
    area_km2: float,
    buildings: int | None = None,
    max_buildings: int = MODEL_MAX_BUILDINGS,
    max_area_km2: float = MODEL_MAX_AREA_KM2,
) -> str | None:
    """Komunikat bramki albo None. `buildings=None` znaczy „jeszcze nie pytalismy bazy".

    Wolamy to dwa razy: raz przed zapytaniem do bazy (sama powierzchnia) i raz po policzeniu
    budynkow. Dzieki temu za duzy prostokat nie kosztuje ani jednego zapytania, a prostokat maly
    powierzchnia, lecz gesto zabudowany, i tak zostanie zatrzymany przed cudzym 413.

    Limity sa argumentami, a nie odczytem stalych: nalezą do uruchomionej uslugi modelu, wiec trasa
    podaje je z konfiguracji. Domyslne wartosci opisuja usluge, ktora stawiamy u siebie.
    """
    over: list[str] = []
    if area_km2 > max_area_km2:
        over.append(f"is {format_km2(area_km2)} km²")
    if buildings is not None and buildings > max_buildings:
        over.append(f"has {buildings:,} buildings")
    if not over:
        return None
    return LIMIT_MESSAGE.format(
        max_buildings=max_buildings,
        max_area=format_km2(max_area_km2),
        actual=" and ".join(over),
    )


async def count_buildings(pool: Any, bbox: BoundingBox, timeout: float) -> int:
    """Ile budynkow OSM siedzi w prostokacie. Jedyne zapytanie bramki."""
    async with pool.connection(timeout=timeout) as connection:
        cursor = await connection.execute(BUILDING_COUNT_SQL, bbox_parameters(bbox))
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


# --- plan podzialu na kawalki mieszczace sie w limitach modelu -----------------------------------
#
# Wstrzykiwany licznik, zeby funkcja podzialu nie znala ani puli, ani SQL-a. Trasa podaje tu
# domkniecie na `count_buildings`, a test — slownik albo funkcje gestosci.
BuildingCounter = Callable[[BoundingBox], Awaitable[int]]


def bbox_is_degenerate(bbox: BoundingBox) -> bool:
    """Prostokat o zerowej albo ujemnej szerokosci lub wysokosci. Taki nie ma prawa trafic do planu:
    `ST_MakeEnvelope` przyjmie go bez protestu, a model dostalby zaznaczenie bez powierzchni."""
    return bbox.north <= bbox.south or bbox.east <= bbox.west


def bbox_sides_m(bbox: BoundingBox) -> tuple[float, float]:
    """Szerokosc i wysokosc prostokata w METRACH, nie w stopniach.

    Bez tego przeliczenia „dluzszy bok" znaczylby „wiecej stopni", a na 51. stopniu szerokosci
    stopien dlugosci ma ~70 km wobec ~111 km stopnia szerokosci. Kwadrat w stopniach jest tam
    prostokatem lezacym, wiec podzial szedlby uparcie po dlugosci i kawalki wychodzilyby coraz
    wezsze — a to wprost pogarsza stosunek dlugosci granicy do powierzchni, czyli liczbe budynkow
    ocenianych dwa razy.
    """
    height_m = radians(bbox.north - bbox.south) * EARTH_RADIUS_M
    width_m = radians(bbox.east - bbox.west) * EARTH_RADIUS_M * cos(radians((bbox.north + bbox.south) / 2.0))
    return (width_m, height_m)


def split_bbox(bbox: BoundingBox) -> tuple[BoundingBox, BoundingBox] | None:
    """Prostokat na POL po dluzszym boku. `None`, gdy podzial nie ma sensu numerycznego.

    Dlaczego na pol, a nie na cwiartki: cwiartki zawsze mnoza liczbe kawalkow przez cztery, wiec
    prostokat przekraczajacy limit o 20% rozpada sie na cztery zapytania do modelu po ~30% limitu,
    zamiast na dwa po ~60%. Kazde zapytanie do modelu to kilkadziesiat sekund inferencji na CPU
    (40 ms na dach) plus pobranie kafli, wiec liczba zapytan jest tu prawdziwym kosztem — nie
    chcemy jej zawyzac o czynnik dwa dla wygody kodu. Ciecie po dluzszym boku trzyma przy tym
    kawalki blisko kwadratu, czyli utrzymuje krotka granice; cwiartkowanie waskiego pasa cielo by
    go takze wzdluz boku, ktory jest juz krotki.
    """
    width_m, height_m = bbox_sides_m(bbox)
    if width_m >= height_m:
        middle = (bbox.west + bbox.east) / 2.0
        if not bbox.west < middle < bbox.east:  # skonczona precyzja float: dalej dzielic nie ma czym
            return None
        west_half = BoundingBox(south=bbox.south, west=bbox.west, north=bbox.north, east=middle)
        east_half = BoundingBox(south=bbox.south, west=middle, north=bbox.north, east=bbox.east)
        return (west_half, east_half)
    middle = (bbox.south + bbox.north) / 2.0
    if not bbox.south < middle < bbox.north:
        return None
    south_half = BoundingBox(south=bbox.south, west=bbox.west, north=middle, east=bbox.east)
    north_half = BoundingBox(south=middle, west=bbox.west, north=bbox.north, east=bbox.east)
    return (south_half, north_half)


def chunk_fits(
    area_km2: float,
    buildings: int,
    max_buildings: int = MODEL_MAX_BUILDINGS,
    max_area_km2: float = MODEL_MAX_AREA_KM2,
) -> bool:
    """Czy kawalek przejdzie przez bramke `/area/analyze`. Oba limity, granica ostra.

    `<=`, a nie `<`: kawalek z dokladnie `max_buildings` budynkami usluga przyjmuje, bo bramka
    odrzuca dopiero `buildings > max_buildings`. Zamiana na `<` dzielilaby prostokaty, ktore i tak
    by przeszly — jedno zapytanie do modelu wiecej za nic.
    """
    return buildings <= max_buildings and area_km2 <= max_area_km2


async def plan_chunks(
    bbox: BoundingBox,
    count: BuildingCounter,
    max_buildings: int = MODEL_MAX_BUILDINGS,
    max_area_km2: float = MODEL_MAX_AREA_KM2,
    max_depth: int = MAX_CHUNK_DEPTH,
) -> AreaPlan:
    """Zaznaczenie na liste prostokatow, z ktorych KAZDY przejdzie bramke modelu.

    To jest tylko plan. Ta funkcja **nie wola modelu** ani razu — analize robi front, wysylajac
    kolejne kawalki do `/api/area/analyze` i pokazujac wyniki w miare ich splywania. Jedyna rzecz,
    ktorej tu pytamy, to licznik budynkow w bazie.

    Kawalki **pokrywaja caly prostokat i nie zachodza na siebie** (poza wspolnymi krawedziami):
    kazde ciecie dzieli prostokat na pol, wiec sumy powierzchni sie zgadzaja. Z listy wypadaja
    tylko kawalki **bez ani jednego budynku** — pytanie modelu o pusta lake to kilkanascie sekund
    za odpowiedz „zero".

    **Budynek stojacy na granicy dwoch kawalkow trafi do dwoch zapytan do modelu i to jest
    zamierzone.** Bramka liczy budynki operatorem `&&`, czyli po obwiedniach, wiec dach przeciety
    linia ciecia nalezy do obu kawalkow; nie da sie tego uniknac, ciac prostokatami. Front
    deduplikuje wyniki po `osm_id` i to jest wlasciwe miejsce na te operacje. **Nie „naprawiaj"
    tego przycinaniem geometrii do kawalka**: model dopasowuje budynki po `source_id` z tego samego
    snapshotu OSM, a nie geometrycznie, wiec przycinanie nie zmienilo by tego, co odda usluga —
    zmienilo by tylko liczbe w `buildings` na liczbe, ktorej bramka nie liczy. Skala zjawiska jest
    mala: granica jest jednowymiarowa, a dachy maja rzedu 10 m, wiec przy kawalku 1 km chodzi
    o promile.

    Podzial jest rekurencyjny i zstepujacy, a licznik pada tylko tam, gdzie jest potrzebny:
    najpierw JEDNO zapytanie na caly prostokat, a potem po dwa na kazde ciecie — i dzielimy
    wylacznie te kawalki, ktore przebijaja limit. Prostokat mieszczacy sie w limicie kosztuje wiec
    jedno zapytanie, a podzial na N prostokatow koncowych (liczac te puste, ktore wypadaja z listy)
    kosztuje `2N - 1`. Pomiary na zywej bazie: 691 budynkow pod Zwoleniem to 2 kawalki i
    3 zapytania w 50 ms, 3 310 budynkow na 7,6 km² w Warszawie to 12 kawalkow i 23 zapytania
    w 330 ms.

    Czego tu swiadomie NIE ma: odejmowania „licznik rodzica minus licznik jednej polowy" zamiast
    drugiego zapytania. Wyszlaby liczba za mala, bo budynki na granicy licza sie w obu polowkach,
    a suma polowek jest wieksza od rodzica.

    Kolejnosc kawalkow jest powtarzalna i przestrzennie zwarta (zachod przed wschodem, poludnie
    przed polnoca, w glab), wiec front analizuje sasiadujace prostokaty po kolei i trafia w cache
    kafli uslugi, zamiast skakac po mapie.

    `truncated` znaczy „przerwalismy podzial": po `max_depth` cieciach (czyli przy `MAX_CHUNKS`
    kawalkach) zostal fragment, ktory nadal nie miesci sie w limicie. Taki fragment **wypada
    z listy**, bo kawalek, ktory dostanie 400, jest gorszy niz jego brak; `buildings` dotyczy
    calego zaznaczenia, wiec front widzi, ze suma po kawalkach jest mniejsza, i moze o tym
    powiedziec.

    Kiedy to naprawde wystepuje — zmierzone, nie oszacowane: zaznaczenie 24,2 km² w centrum
    Warszawy (10 631 budynkow) dzieli sie na 31 kawalkow pokrywajacych 98,4% powierzchni, a jeden
    blok o powierzchni 0,38 km² ma ponad 500 budynkow i wypada. Podniesienie `MAX_CHUNKS` do 128
    domykaloby ten przypadek kosztem dwoch dodatkowych zapytan (65 zamiast 63) — i swiadomie tego
    nie robimy: 33 kawalki po ~350 dachow to 11 000 dachow, czyli od kilkunastu minut do
    poltorej godziny inferencji, wiec `truncated` jest tam wlasciwa odpowiedzia („zmniejsz
    zaznaczenie"), a nie usterka do obejscia.
    """
    if bbox_is_degenerate(bbox):
        # Trasa odrzuca to wczesniej wlasnym 400; tutaj chodzi o to, zeby nie pytac bazy o nic.
        return AreaPlan(chunks=[], buildings=0, area_km2=0.0, truncated=False)
    total = await count(bbox)
    chunks, truncated = await _divide(bbox, total, 0, count, max_buildings, max_area_km2, max_depth)
    return AreaPlan(
        chunks=chunks,
        buildings=total,
        area_km2=round(bbox_area_km2(bbox), 3),
        truncated=truncated,
    )


async def _divide(
    bbox: BoundingBox,
    buildings: int,
    depth: int,
    count: BuildingCounter,
    max_buildings: int,
    max_area_km2: float,
    max_depth: int,
) -> tuple[list[AreaChunk], bool]:
    """Jeden poziom rekurencji: albo kawalek gotowy, albo dwie polowki. Liczba budynkow jest
    argumentem, bo policzyl ja wolajacy — inaczej kazdy prostokat bylby liczony dwa razy."""
    if buildings <= 0:
        return ([], False)  # pusta laka: ani kawalka, ani zapytania do modelu
    area_km2 = bbox_area_km2(bbox)
    if chunk_fits(area_km2, buildings, max_buildings, max_area_km2):
        return ([AreaChunk(bbox=bbox, buildings=buildings)], False)
    halves = split_bbox(bbox) if depth < max_depth else None
    if halves is None:
        return ([], True)  # nie ma jak dzielic dalej — lepiej nie oddac nic niz kawalek z 400
    chunks: list[AreaChunk] = []
    truncated = False
    for half in halves:
        counted = await count(half)
        found, cut = await _divide(half, counted, depth + 1, count, max_buildings, max_area_km2, max_depth)
        chunks.extend(found)
        truncated = truncated or cut
    return (chunks, truncated)


def facts_from_rows(rows: Sequence[Sequence[Any]]) -> dict[int, BuildingFacts]:
    return {
        int(row[0]): BuildingFacts(
            area_m2=float(row[1]) if row[1] is not None else None,
            listed=bool(row[2]),
        )
        for row in rows
    }


async def read_building_facts(pool: Any, osm_ids: Sequence[int], timeout: float) -> dict[int, BuildingFacts]:
    """Powierzchnia i status rejestrowy dla wszystkich budynkow naraz — jedno zapytanie.

    Pusta lista nie jest bledem i nie jest powodem, zeby ruszac baze: model mogl nie odeslac
    ani jednego budynku (pusty prostokat).
    """
    if not osm_ids:
        return {}
    async with pool.connection(timeout=timeout) as connection:
        # Kolumna jest tekstowa, wiec parametrem jest tablica tekstow.
        cursor = await connection.execute(BUILDING_FACTS_SQL, {"ids": [str(osm_id) for osm_id in osm_ids]})
        rows = await cursor.fetchall()
    return facts_from_rows(rows or [])


def analysis_from_model(
    result: AreaModelResult,
    facts: dict[int, BuildingFacts],
    limit: int = MAX_ANALYSED_BUILDINGS,
) -> AreaAnalysis:
    """Odpowiedz modelu plus fakty z bazy na liste budynkow i statystyki. Cala arytmetyka jest tu.

    Budynek, ktorego nasza baza nie zna, NIE wchodzi do wynikow — liczy go `unknown_to_us`.
    Wczesniej dostawal `listed=False` i ladowal w `suspected_not_listed`, czyli w liczbie
    prowadzacej calej aplikacji. To bylo twierdzenie bez pokrycia: „nie ma go w naszej bazie"
    nie znaczy „nikt go nie zglosil". Przy wspolnym snapshocie OSM to sie nie zdarza, ale liczba,
    na ktora patrzy urzednik, nie moze dac sie zawyzyc rozjazdem danych.
    """
    scored: list[AnalysedBuilding] = []
    no_result = 0
    unknown_to_us = 0
    for building in result.buildings:
        if not building.scored or building.probability is None:
            # `low_quality`, `imagery_error`, `geometry_error` i wszystko inne: nieznane, nie czyste.
            no_result += 1
            continue
        known = facts.get(building.osm_id)
        if known is None or known.area_m2 is None:
            # O jego statusie rejestrowym nie wiemy nic, wiec nie wolno go policzyc po zadnej
            # stronie. Widoczny jako `unknown_to_us`, zeby rozjazd snapshotow nie byl niewidzialny.
            unknown_to_us += 1
            continue
        scored.append(
            AnalysedBuilding(
                id=building.osm_id,
                probability=building.probability,
                listed=known.listed,
                area_m2=known.area_m2,
                geometry=building.geometry,
            )
        )

    analysed = len(scored)
    suspected_buildings = [building for building in scored if building.suspected]
    suspected = len(suspected_buildings)
    suspected_listed = sum(1 for building in suspected_buildings if building.listed)
    # Odejmowanie, a nie drugie zliczanie: dzieki temu suma obu skladnikow zawsze jest rowna
    # `suspected` i nie da sie pomylic kierunku przy zmianie warunku.
    suspected_not_listed = suspected - suspected_listed
    listed_not_suspected = sum(1 for building in scored if building.listed and not building.suspected)
    suspected_roof_area_m2 = round(sum(building.area_m2 for building in suspected_buildings), 1)

    stats = AreaAnalysisStats(
        analysed=analysed,
        no_result=no_result,
        suspected=suspected,
        # Mianownikiem jest `analysed`, nigdy `analysed + no_result`: dachy bez oceny sa nieznane,
        # a doliczenie ich zanizyloby udzial tam, gdzie zdjecie bylo najgorsze.
        suspected_share=round(suspected / analysed, 4) if analysed else 0.0,
        suspected_not_listed=suspected_not_listed,
        suspected_listed=suspected_listed,
        listed_not_suspected=listed_not_suspected,
        suspected_roof_area_m2=suspected_roof_area_m2,
        threshold=SUSPECTED_THRESHOLD,
        model_name=result.model_name,
        unknown_to_us=unknown_to_us,
    )
    # Najbardziej podejrzane na gorze, remisy po `osm_id` — kolejnosc ma byc powtarzalna, bo ta
    # lista idzie do panelu obok mapy i do ewentualnego eksportu.
    ordered = sorted(scored, key=lambda building: (-building.probability, building.id))
    return AreaAnalysis(stats=stats, buildings=ordered[:limit], truncated=len(ordered) > limit)
