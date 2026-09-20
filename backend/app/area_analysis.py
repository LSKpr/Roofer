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
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.area import BoundingBox, format_km2
from app.prediction import (
    MODEL_MAX_AREA_KM2,
    MODEL_MAX_BUILDINGS,
    SUSPECTED_THRESHOLD,
    AreaModelResult,
)

# Gorna granica listy budynkow w odpowiedzi. Przy bramce 100 budynkow nie da sie jej dzisiaj
# przekroczyc — jest po to, zeby podniesienie limitu po tamtej stronie nie zamienilo odpowiedzi
# w megabajt geometrii po cichu. Nadwyzke zglasza pole `truncated`, tak samo jak w /area/scan.
MAX_ANALYSED_BUILDINGS = 100

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
    "The model accepts up to {max_buildings} buildings and {max_area} km²; this area {actual} "
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


def corners(bbox: BoundingBox) -> tuple[float, float, float, float]:
    """Kolejnosc [west, south, east, north] — ta sama, co `BuildingShape.bbox`."""
    return (bbox.west, bbox.south, bbox.east, bbox.north)


def bbox_parameters(bbox: BoundingBox) -> dict[str, float]:
    return {"south": bbox.south, "west": bbox.west, "north": bbox.north, "east": bbox.east}


def model_limit_problem(area_km2: float, buildings: int | None = None) -> str | None:
    """Komunikat bramki albo None. `buildings=None` znaczy „jeszcze nie pytalismy bazy".

    Wolamy to dwa razy: raz przed zapytaniem do bazy (sama powierzchnia) i raz po policzeniu
    budynkow. Dzieki temu za duzy prostokat nie kosztuje ani jednego zapytania, a prostokat maly
    powierzchnia, lecz gesto zabudowany, i tak zostanie zatrzymany przed cudzym 413.
    """
    over: list[str] = []
    if area_km2 > MODEL_MAX_AREA_KM2:
        over.append(f"is {format_km2(area_km2)} km²")
    if buildings is not None and buildings > MODEL_MAX_BUILDINGS:
        over.append(f"has {buildings:,} buildings")
    if not over:
        return None
    return LIMIT_MESSAGE.format(
        max_buildings=MODEL_MAX_BUILDINGS,
        max_area=format_km2(MODEL_MAX_AREA_KM2),
        actual=" and ".join(over),
    )


async def count_buildings(pool: Any, bbox: BoundingBox, timeout: float) -> int:
    """Ile budynkow OSM siedzi w prostokacie. Jedyne zapytanie bramki."""
    async with pool.connection(timeout=timeout) as connection:
        cursor = await connection.execute(BUILDING_COUNT_SQL, bbox_parameters(bbox))
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


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
