"""Podzial zaznaczenia na kawalki mieszczace sie w limitach modelu — bez sieci i bez bazy.

Wiekszosc testow wola `plan_chunks` wprost z podstawionym licznikiem, bo cala tresc tego endpointu
to geometria i arytmetyka: ile ciec, gdzie i ile zapytan to kosztuje. Licznik jest wstrzykiwany,
wiec da sie opisac zabudowe, ktora w prawdziwej bazie trzeba by najpierw zaimportowac — gesta,
pusta w polowie albo patologicznie gesta.

Dwie rzeczy, ktore te testy pilnuja szczegolnie mocno:

* **liczba zapytan do bazy.** Kazde wejscie w `connection()` jest jednym zapytaniem, wiec asercje na
  `len(pool.statements)` sa tu asercjami na koszt algorytmu. Podzial, ktory liczy budynki w calym
  prostokacie na kazdym poziomie, przeszedlby wszystkie testy na ksztalt kawalkow i wywrocil te.
* **granica limitu.** Kawalek z dokladnie `max_buildings` budynkami jest w porzadku, z jednym
  wiecej — nie. Zamiana `<=` na `<` w `chunk_fits` nie psuje ani jednego kawalka, tylko dokłada
  zapytania do modelu, wiec musi ja zlapac osobny test.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from itertools import combinations
from math import nextafter
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.area import AREA_KM2_DECIMALS, BoundingBox, bbox_area_km2
from app.area_analysis import (
    MAX_CHUNK_DEPTH,
    MAX_CHUNKS,
    AreaChunk,
    bbox_is_degenerate,
    bbox_sides_m,
    chunk_fits,
    plan_chunks,
    split_bbox,
)
from app.config import Settings
from app.main import create_app
from app.prediction import MODEL_MAX_AREA_KM2, MODEL_MAX_BUILDINGS

PLAN_PATH = "/api/area/plan"

# Prostokat pod Zwoleniem, ktory dziala jako przyklad od poczatku tego zadania: 691 budynkow, czyli
# o 191 za duzo na jedno zapytanie do modelu, przy 0,69 km² — wiec o podzial prosi sama zabudowa,
# a nie powierzchnia.
DENSE_SELECTION = {"sw": {"lng": 21.5745, "lat": 51.3555}, "ne": {"lng": 21.5865, "lat": 51.3629}}
LIVE_BUILDINGS = 691

# 11,4 km², czyli ponad limit powierzchni (10 km²) i ponizej limitu skanu rejestru (25 km²).
WIDE_SELECTION = {"sw": {"lng": 21.0, "lat": 52.0}, "ne": {"lng": 21.05, "lat": 52.03}}

SETTINGS = Settings(database_url="postgresql://unused", prediction_provider="mock")


# --- atrapy licznika ------------------------------------------------------------------------------


def box(payload: dict[str, dict[str, float]]) -> BoundingBox:
    return BoundingBox(
        south=payload["sw"]["lat"],
        west=payload["sw"]["lng"],
        north=payload["ne"]["lat"],
        east=payload["ne"]["lng"],
    )


Density = Callable[[BoundingBox], int]


def spread(total: int, over: BoundingBox) -> Density:
    """Budynki rozlozone rownomiernie: kawalek dostaje tyle, ile mu sie nalezy z powierzchni.

    Rozklad rownomierny jest tu wybrany celowo, bo pozwala policzyc oczekiwany wynik na piechote:
    kazde ciecie dzieli powierzchnie dokladnie na pol, wiec po dwoch cieciach kawalek ma cwiartke
    budynkow. Dzieki temu test moze twierdzic „cztery kawalki po 334", a nie tylko „jakos sie
    podzielilo".
    """
    whole = bbox_area_km2(over)

    def counted(bbox: BoundingBox) -> int:
        return round(total * bbox_area_km2(bbox) / whole)

    return counted


def everywhere(count: int) -> Density:
    """Ta sama liczba w kazdym prostokacie, niezaleznie od jego rozmiaru: zabudowa niemozliwa,
    ale dokladnie taka, o ktora chodzi w bezpieczniku `MAX_CHUNKS`."""
    return lambda _bbox: count


def with_hotspot(base: Density, hotspot: BoundingBox, count: int) -> Density:
    """Jedna kieszen, ktorej nie da sie pociac do limitu, i normalna zabudowa wokol."""

    def counted(bbox: BoundingBox) -> int:
        return count if overlaps(bbox, hotspot) else base(bbox)

    return counted


def counter_of(density: Density) -> tuple[list[BoundingBox], Callable[[BoundingBox], Awaitable[int]]]:
    """Licznik do wstrzykniecia plus lista prostokatow, o ktore zapytal — czyli koszt w zapytaniach."""
    asked: list[BoundingBox] = []

    async def count(bbox: BoundingBox) -> int:
        asked.append(bbox)
        return density(bbox)

    return (asked, count)


# --- atrapa puli ----------------------------------------------------------------------------------


class FakeCursor:
    def __init__(self, rows: Sequence[Sequence[Any]]) -> None:
        self.rows = list(rows)

    async def fetchone(self) -> Sequence[Any] | None:
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, pool: "CountingPool") -> None:
        self.pool = pool

    async def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.pool.statements.append((sql, params))
        asked = BoundingBox(
            south=params["south"],
            west=params["west"],
            north=params["north"],
            east=params["east"],
        )
        return FakeCursor([(self.pool.density(asked),)])


class CountingPool:
    """Pula bez bazy, ktora liczy budynki z podanej funkcji gestosci.

    `statements` rosnie o jeden wpis na kazde zapytanie, wiec jego dlugosc jest miara kosztu
    podzialu — i o to w polowie tych testow chodzi.
    """

    def __init__(self, density: Density, error: BaseException | None = None) -> None:
        self.density = density
        self.error = error
        self.statements: list[tuple[str, Any]] = []

    async def open(self, wait: bool = False) -> None:
        return None

    async def close(self) -> None:
        return None

    @asynccontextmanager
    async def connection(self, timeout: float | None = None) -> AsyncIterator[FakeConnection]:
        if self.error is not None:
            raise self.error
        yield FakeConnection(self)


def client_with(pool: CountingPool, settings: Settings = SETTINGS) -> TestClient:
    return TestClient(create_app(settings, pool_factory=lambda _settings: pool))


# --- pomoce do asercji geometrycznych -------------------------------------------------------------


def overlaps(first: BoundingBox, second: BoundingBox) -> bool:
    """Czy wnetrza dwoch prostokatow maja czesc wspolna. Wspolna krawedz to NIE zachodzenie:
    kawalki sasiaduja i musza sasiadowac, zeby pokrywac cale zaznaczenie."""
    return min(first.east, second.east) > max(first.west, second.west) and min(first.north, second.north) > max(
        first.south, second.south
    )


def corners_of(chunk: AreaChunk) -> tuple[float, float, float, float]:
    return (chunk.bbox.west, chunk.bbox.south, chunk.bbox.east, chunk.bbox.north)


def pairs(chunks: Sequence[AreaChunk]) -> Iterator[tuple[AreaChunk, AreaChunk]]:
    return combinations(chunks, 2)


# --- kawalek, ktory sie miesci --------------------------------------------------------------------


async def test_a_selection_inside_the_limits_is_one_chunk_equal_to_the_selection() -> None:
    """Nie ma po co ciac prostokata, ktory model przyjmie w calosci — i nie ma po co dodawac
    zapytan: caly plan kosztuje wtedy jeden licznik."""
    asked, count = counter_of(everywhere(400))
    selection = box(DENSE_SELECTION)

    plan = await plan_chunks(selection, count)

    assert [corners_of(chunk) for chunk in plan.chunks] == [
        (selection.west, selection.south, selection.east, selection.north)
    ]
    assert plan.chunks[0].buildings == 400
    assert (plan.buildings, plan.truncated) == (400, False)
    assert plan.area_km2 == round(bbox_area_km2(selection), AREA_KM2_DECIMALS)
    assert len(asked) == 1


async def test_exactly_at_the_limit_is_still_one_chunk() -> None:
    """Granica jest ostra i ta strona granicy jest ta trudniejsza do zauwazenia: bramka odrzuca
    dopiero `buildings > max_buildings`, wiec dzielenie prostokata z dokladnie `max_buildings`
    budynkami dokladaloby zapytanie do modelu za nic."""
    asked, count = counter_of(everywhere(MODEL_MAX_BUILDINGS))

    plan = await plan_chunks(box(DENSE_SELECTION), count)

    assert len(plan.chunks) == 1
    assert plan.chunks[0].buildings == MODEL_MAX_BUILDINGS
    assert len(asked) == 1


async def test_one_building_over_the_limit_forces_a_split() -> None:
    density = spread(MODEL_MAX_BUILDINGS + 1, box(DENSE_SELECTION))
    _asked, count = counter_of(density)

    plan = await plan_chunks(box(DENSE_SELECTION), count)

    assert len(plan.chunks) == 2
    assert plan.buildings == MODEL_MAX_BUILDINGS + 1


# --- gesta zabudowa: kilka kawalkow ---------------------------------------------------------------


async def dense_plan(total: int = 1338) -> Any:
    """Prostokat z 1338 budynkami: dwa poziomy ciecia, cztery kawalki po 334."""
    selection = box(DENSE_SELECTION)
    _asked, count = counter_of(spread(total, selection))
    return await plan_chunks(selection, count)


async def test_every_chunk_of_a_dense_selection_fits_the_model_limit() -> None:
    plan = await dense_plan()

    assert plan.buildings == 1338  # liczba dla CALEGO prostokata, nie suma po kawalkach
    assert len(plan.chunks) == 4
    # Nie po 334,5, bo poludniowa polowka ma na kuli wieksza powierzchnie niz polnocna: przy
    # rownomiernej gestosci wypada w niej o jeden budynek wiecej.
    assert [chunk.buildings for chunk in plan.chunks] == [335, 334, 335, 334]
    assert all(chunk.buildings <= MODEL_MAX_BUILDINGS for chunk in plan.chunks)
    assert all(bbox_area_km2(chunk.bbox) <= MODEL_MAX_AREA_KM2 for chunk in plan.chunks)
    assert plan.truncated is False


async def test_the_chunks_cover_the_whole_selection() -> None:
    """Suma powierzchni kawalkow to powierzchnia zaznaczenia. Kawalek zgubiony przy ciecu byl by
    fragmentem mapy, ktorego model nigdy nie zobaczy, a nikt by tego nie zauwazyl."""
    plan = await dense_plan()

    total_km2 = sum(bbox_area_km2(chunk.bbox) for chunk in plan.chunks)
    assert total_km2 == pytest.approx(bbox_area_km2(box(DENSE_SELECTION)), rel=1e-12)


async def test_the_chunks_do_not_overlap() -> None:
    """Wspolna krawedz owszem, wspolne wnetrze nie: pokrywanie sie kawalkow to ten sam budynek
    wyslany do modelu dwa razy, czyli kilkadziesiat sekund inferencji za nic."""
    plan = await dense_plan()

    assert [pair for pair in pairs(plan.chunks) if overlaps(pair[0].bbox, pair[1].bbox)] == []


async def test_the_chunk_corners_come_from_halving_and_meet_exactly() -> None:
    """Krawedzie sasiadow to ta sama liczba, nie dwie zaokraglone — inaczej miedzy kawalkami
    zostalby pasek, ktorego nikt nie przeanalizuje."""
    plan = await dense_plan()

    edges = {chunk.bbox.west for chunk in plan.chunks} | {chunk.bbox.east for chunk in plan.chunks}
    selection = box(DENSE_SELECTION)
    middle = (selection.west + selection.east) / 2.0
    assert edges == {selection.west, middle, selection.east}


# --- puste kawalki --------------------------------------------------------------------------------


async def test_empty_chunks_are_dropped_instead_of_being_sent_to_the_model() -> None:
    """Pytanie modelu o pusta lake to kilkanascie sekund czekania na odpowiedz „zero"."""
    selection = box(DENSE_SELECTION)
    middle = (selection.west + selection.east) / 2.0
    dense = spread(1400, selection)

    def only_east(bbox: BoundingBox) -> int:
        return 0 if bbox.east <= middle else dense(bbox)

    _asked, count = counter_of(only_east)
    plan = await plan_chunks(selection, count)

    assert plan.chunks != []
    assert all(chunk.buildings > 0 for chunk in plan.chunks)
    assert all(chunk.bbox.west >= middle for chunk in plan.chunks)


async def test_a_selection_with_no_buildings_is_an_empty_plan_not_an_error() -> None:
    asked, count = counter_of(everywhere(0))

    plan = await plan_chunks(box(DENSE_SELECTION), count)

    assert plan.chunks == []
    assert (plan.buildings, plan.truncated) == (0, False)
    assert len(asked) == 1  # puste zaznaczenie nie jest powodem, zeby cokolwiek ciac


async def test_an_empty_half_costs_no_further_queries() -> None:
    """Pusta polowa nie jest dzielona: „zero budynkow" wiadomo raz i na zawsze."""
    selection = box(DENSE_SELECTION)
    middle = (selection.west + selection.east) / 2.0
    dense = spread(1400, selection)
    asked, count = counter_of(lambda bbox: 0 if bbox.east <= middle else dense(bbox))

    await plan_chunks(selection, count)

    # 1 na calosc, 2 na pierwsze ciecie, 2 na ciecie zabudowanej polowy (700 > 500) — i nic wiecej.
    assert len(asked) == 5


# --- limit powierzchni ----------------------------------------------------------------------------


async def test_the_area_limit_alone_forces_a_split() -> None:
    """11,4 km² z dziesiecioma budynkami: model przyjmuje 500 budynkow, ale tylko 10 km²."""
    selection = box(WIDE_SELECTION)
    assert bbox_area_km2(selection) > MODEL_MAX_AREA_KM2
    _asked, count = counter_of(spread(10, selection))

    plan = await plan_chunks(selection, count)

    assert len(plan.chunks) == 2
    assert all(bbox_area_km2(chunk.bbox) <= MODEL_MAX_AREA_KM2 for chunk in plan.chunks)
    assert [chunk.buildings for chunk in plan.chunks] == [5, 5]
    assert plan.truncated is False


async def test_both_limits_must_be_satisfied_at_once() -> None:
    """Duzy obszar i gesta zabudowa razem: dzielimy do momentu, w ktorym przechodza oba warunki."""
    selection = box(WIDE_SELECTION)
    _asked, count = counter_of(spread(4000, selection))

    plan = await plan_chunks(selection, count)

    assert plan.chunks != []
    for chunk in plan.chunks:
        assert chunk.buildings <= MODEL_MAX_BUILDINGS
        assert bbox_area_km2(chunk.bbox) <= MODEL_MAX_AREA_KM2


# --- koszt w zapytaniach --------------------------------------------------------------------------


async def test_a_typical_split_costs_one_query_per_rectangle_it_looked_at() -> None:
    """691 budynkow to jedno ciecie: licznik na calosc plus po jednym na polowke. Trzy zapytania.

    Ta liczba jest tu najwazniejsza. Podzial „policz wszystko na kazdym poziomie" albo liczenie
    calosci ponownie po kazdym ciecu daje te same kawalki i wywraca dopiero ten test.
    """
    pool = CountingPool(spread(LIVE_BUILDINGS, box(DENSE_SELECTION)))

    with client_with(pool) as client:
        body = client.post(PLAN_PATH, json=DENSE_SELECTION).json()

    assert body["buildings"] == LIVE_BUILDINGS
    assert [chunk["buildings"] for chunk in body["chunks"]] == [346, 346]
    assert len(pool.statements) == 3


async def test_the_number_of_queries_is_twice_the_number_of_rectangles_minus_one() -> None:
    """Niezmiennik kosztu: drzewo binarne o N lisciach ma N-1 wezlow wewnetrznych, kazdy pyta
    o dwoje dzieci, plus jedno zapytanie na korzen. Dla czterech kawalkow to siedem zapytan."""
    selection = box(DENSE_SELECTION)
    asked, count = counter_of(spread(1338, selection))

    plan = await plan_chunks(selection, count)

    assert len(plan.chunks) == 4
    assert len(asked) == 2 * len(plan.chunks) - 1 == 7


async def test_the_same_rectangle_is_never_counted_twice() -> None:
    selection = box(DENSE_SELECTION)
    asked, count = counter_of(spread(1338, selection))

    await plan_chunks(selection, count)

    assert len(asked) == len({(b.west, b.south, b.east, b.north) for b in asked})


# --- bezpiecznik MAX_CHUNKS -----------------------------------------------------------------------


async def test_a_pathological_density_stops_at_max_chunks_and_admits_it() -> None:
    """Zabudowa, ktorej nie da sie pociac: 10 000 budynkow w kazdym prostokacie, takze po szescdziesieciu
    czterech cieciach. Oddajemy pusta liste z `truncated`, a nie kawalki, ktore dostana 400 —
    i konczymy na twardej liczbie zapytan, a nie na setkach."""
    asked, count = counter_of(everywhere(10_000))

    plan = await plan_chunks(box(DENSE_SELECTION), count)

    assert plan.truncated is True
    assert plan.chunks == []
    assert plan.buildings == 10_000
    assert len(asked) == 2 * MAX_CHUNKS - 1 == 127


async def test_truncation_keeps_the_chunks_it_managed_to_cut() -> None:
    """Jedna kieszen nie do pociecia nie przekresla reszty planu: to, co da sie przeanalizowac,
    front ma dostac, a `truncated` mowi, ze zaznaczenie nie jest pokryte w calosci."""
    selection = box(DENSE_SELECTION)
    middle = (selection.west + selection.east) / 2.0
    hotspot = BoundingBox(south=selection.south, west=selection.west, north=selection.north, east=middle)
    _asked, count = counter_of(with_hotspot(spread(600, selection), hotspot, 10_000))

    plan = await plan_chunks(selection, count)

    assert plan.truncated is True
    assert [chunk.buildings for chunk in plan.chunks] == [300]
    assert plan.chunks[0].bbox.west == middle  # zostala wschodnia polowa, zachodnia byla patologiczna


async def test_the_depth_limit_is_the_chunk_limit_expressed_in_cuts() -> None:
    """Kazde ciecie dzieli na pol, wiec 64 kawalki to dokladnie szesc poziomow. Gdyby ktos podniosl
    `MAX_CHUNKS` do liczby, ktora nie jest potega dwojki, ta asercja to zglosi."""
    assert 2**MAX_CHUNK_DEPTH == MAX_CHUNKS


async def test_a_lower_depth_limit_truncates_earlier() -> None:
    selection = box(DENSE_SELECTION)
    asked, count = counter_of(everywhere(10_000))

    plan = await plan_chunks(selection, count, max_depth=2)

    assert (plan.chunks, plan.truncated) == ([], True)
    assert len(asked) == 2 * 4 - 1 == 7


# --- geometria ciecia -----------------------------------------------------------------------------


def test_the_cut_goes_along_the_longer_side_measured_in_metres() -> None:
    """Kwadrat w stopniach na 51. paraleli jest prostokatem lezacym w metrach (700 x 1112 m), wiec
    ciecie musi iss w poprzek — po szerokosci geograficznej. Porownanie samych stopni cieloby go
    po dlugosci i kawalki wychodzilyby coraz wezsze."""
    square_in_degrees = BoundingBox(south=51.0, west=21.0, north=51.01, east=21.01)
    width_m, height_m = bbox_sides_m(square_in_degrees)
    assert width_m < height_m

    halves = split_bbox(square_in_degrees)

    assert halves is not None
    south_half, north_half = halves
    assert (south_half.west, south_half.east) == (21.0, 21.01)  # dlugosc nietknieta
    assert south_half.north == north_half.south == (51.0 + 51.01) / 2.0
    assert (south_half.south, north_half.north) == (51.0, 51.01)


def test_a_lying_rectangle_is_cut_along_the_longitude() -> None:
    lying = BoundingBox(south=51.0, west=21.0, north=51.001, east=21.01)

    halves = split_bbox(lying)

    assert halves is not None
    west_half, east_half = halves
    assert west_half.east == east_half.west == (21.0 + 21.01) / 2.0
    assert (west_half.south, west_half.north) == (51.0, 51.001)  # szerokosc nietknieta


def test_the_two_halves_tile_the_parent_without_a_gap() -> None:
    parent = BoundingBox(south=51.3555, west=21.5745, north=51.3629, east=21.5865)

    halves = split_bbox(parent)

    assert halves is not None
    assert sum(bbox_area_km2(half) for half in halves) == pytest.approx(bbox_area_km2(parent), rel=1e-12)
    assert not overlaps(*[half for half in halves])


@pytest.mark.parametrize(
    "bbox",
    [
        BoundingBox(south=51.0, west=21.0, north=51.0, east=21.01),  # zerowa wysokosc
        BoundingBox(south=51.0, west=21.0, north=51.01, east=21.0),  # zerowa szerokosc
        BoundingBox(south=51.01, west=21.0, north=51.0, east=21.01),  # odwrocone rogi
    ],
)
def test_a_degenerate_rectangle_is_recognised_as_such(bbox: BoundingBox) -> None:
    assert bbox_is_degenerate(bbox) is True


def test_there_is_nothing_left_to_cut_at_the_precision_of_a_float() -> None:
    """Dwie kolejne liczby zmiennoprzecinkowe nie maja miedzy soba srodka. Podzial musi wtedy
    powiedziec „nie umiem", a nie oddac kawalka o zerowej szerokosci — bo taki kawalek przeszedlby
    przez `ST_MakeEnvelope` bez protestu i poszedl do modelu jako zaznaczenie bez powierzchni."""
    hair_thin = BoundingBox(
        south=51.0,
        west=21.0,
        north=nextafter(51.0, 52.0),
        east=nextafter(21.0, 22.0),
    )
    assert bbox_is_degenerate(hair_thin) is False  # formalnie poprawny, tylko nieskonczenie maly

    assert split_bbox(hair_thin) is None


async def test_a_degenerate_selection_costs_no_queries_and_no_chunks() -> None:
    """Trasa odrzuca to wlasnym 400, ale sama funkcja tez nie ma prawa pytac bazy o prostokat
    bez powierzchni ani oddac go jako kawalka."""
    asked, count = counter_of(everywhere(1000))
    flat = BoundingBox(south=51.0, west=21.0, north=51.0, east=21.01)

    plan = await plan_chunks(flat, count)

    assert (plan.chunks, plan.buildings, plan.area_km2, plan.truncated) == ([], 0, 0.0, False)
    assert asked == []


async def test_no_chunk_in_a_plan_is_ever_degenerate() -> None:
    selection = box(DENSE_SELECTION)
    _asked, count = counter_of(spread(9000, selection))

    plan = await plan_chunks(selection, count)

    assert plan.chunks != []
    assert [chunk for chunk in plan.chunks if bbox_is_degenerate(chunk.bbox)] == []


# --- caly endpoint --------------------------------------------------------------------------------


def test_the_endpoint_answers_with_chunks_and_the_totals_for_the_whole_selection() -> None:
    pool = CountingPool(spread(1338, box(DENSE_SELECTION)))

    with client_with(pool) as client:
        response = client.post(PLAN_PATH, json=DENSE_SELECTION)

    assert response.status_code == 200
    body = response.json()
    assert body["buildings"] == 1338
    assert body["areaKm2"] == round(bbox_area_km2(box(DENSE_SELECTION)), AREA_KM2_DECIMALS)
    assert body["truncated"] is False
    assert len(body["chunks"]) == 4
    assert body["chunks"][0] == {
        "sw": {"lng": 21.5745, "lat": 51.3555},
        "ne": {"lng": 21.5805, "lat": 51.3592},
        "buildings": 335,
    }
    assert body["chunks"][-1] == {
        "sw": {"lng": 21.5805, "lat": 51.3592},
        "ne": {"lng": 21.5865, "lat": 51.3629},
        "buildings": 334,
    }
    assert set(body.keys()) == {"chunks", "buildings", "areaKm2", "truncated"}


def test_every_chunk_from_the_endpoint_would_pass_the_analyze_gate() -> None:
    """Sens calego endpointu w jednej asercji: kawalek z tej listy nie ma prawa dostac 400."""
    pool = CountingPool(spread(2000, box(WIDE_SELECTION)))

    with client_with(pool) as client:
        body = client.post(PLAN_PATH, json=WIDE_SELECTION).json()

    for chunk in body["chunks"]:
        bbox = BoundingBox(
            south=chunk["sw"]["lat"],
            west=chunk["sw"]["lng"],
            north=chunk["ne"]["lat"],
            east=chunk["ne"]["lng"],
        )
        assert chunk_fits(bbox_area_km2(bbox), chunk["buildings"]) is True


def test_the_endpoint_follows_the_configured_limits_not_the_constants() -> None:
    """Limity naleza do uruchomionej uslugi modelu. Ostrzejsza konfiguracja musi dac wiecej kawalkow,
    inaczej plan obiecuje przejscie przez bramke, ktorej sam nie zna."""
    strict = Settings(
        database_url="postgresql://unused",
        prediction_provider="mock",
        prediction_model_max_buildings=100,
        prediction_model_max_area_km2=4.0,
    )
    density = spread(1338, box(DENSE_SELECTION))

    with client_with(CountingPool(density)) as client:
        default = client.post(PLAN_PATH, json=DENSE_SELECTION).json()
    with client_with(CountingPool(density), strict) as client:
        tighter = client.post(PLAN_PATH, json=DENSE_SELECTION).json()

    assert len(default["chunks"]) == 4
    assert len(tighter["chunks"]) == 16
    assert all(chunk["buildings"] <= 100 for chunk in tighter["chunks"])


def test_the_endpoint_never_calls_the_model() -> None:
    """Plan to plan. Dostawca w tej konfiguracji to atrapa, ktorej `/area/analyze` nie wpuszcza do
    statystyk obszaru — a mimo to plan wychodzi z kodem 200, bo modelu nie dotyka."""
    pool = CountingPool(spread(1338, box(DENSE_SELECTION)))

    with client_with(pool) as client:
        response = client.post(PLAN_PATH, json=DENSE_SELECTION)
        refused = client.post("/api/area/analyze", json=DENSE_SELECTION)

    assert response.status_code == 200
    assert refused.status_code in (400, 503)  # analiza bez modelu nie przechodzi, plan przechodzi
    assert all("count(*)" in sql for sql, _params in pool.statements)


def test_inverted_corners_are_a_400_before_any_query() -> None:
    pool = CountingPool(everywhere(100))
    inverted = {"sw": {"lng": 21.5865, "lat": 51.3629}, "ne": {"lng": 21.5745, "lat": 51.3555}}

    with client_with(pool) as client:
        response = client.post(PLAN_PATH, json=inverted)

    assert response.status_code == 400
    assert "north corner" in response.json()["detail"]
    assert pool.statements == []


def test_a_flat_selection_is_a_400_as_well() -> None:
    pool = CountingPool(everywhere(100))
    flat = {"sw": {"lng": 21.5745, "lat": 51.3555}, "ne": {"lng": 21.5865, "lat": 51.3555}}

    with client_with(pool) as client:
        response = client.post(PLAN_PATH, json=flat)

    assert response.status_code == 400
    assert pool.statements == []


def test_a_dead_database_is_a_503_with_a_message_not_a_500() -> None:
    pool = CountingPool(everywhere(100), error=OSError("connection refused"))

    with client_with(pool) as client:
        response = client.post(PLAN_PATH, json=DENSE_SELECTION)

    assert response.status_code == 503
    assert response.json()["detail"] == "The database is not responding."


def test_an_area_over_the_registry_scan_limit_is_not_this_endpoints_business() -> None:
    """Front wola te trase po udanym skanie, wiec limitu 25 km² tu nie ma: wieksze zaznaczenie
    rozpada sie po prostu na wiecej kawalkow, zamiast dostac odmowe."""
    huge = {"sw": {"lng": 21.0, "lat": 52.0}, "ne": {"lng": 21.2, "lat": 52.1}}
    pool = CountingPool(spread(3000, box(huge)))

    with client_with(pool) as client:
        response = client.post(PLAN_PATH, json=huge)

    assert response.status_code == 200
    body = response.json()
    assert body["areaKm2"] > 25.0
    assert len(body["chunks"]) >= 8
    assert body["truncated"] is False
