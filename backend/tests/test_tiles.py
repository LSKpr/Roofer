from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.dataversion import tile_etag
from app.main import create_app
from app.tiles import (
    DENSITY_COUNT,
    DENSITY_GRID,
    DENSITY_LAYER,
    DENSITY_MIN_ZOOM,
    DENSITY_TILE,
    FEATURE_ID,
    POLYGON_LAYER,
    POLYGON_MIN_ZOOM,
    POLYGON_TILE,
    tile_sql,
    within_grid,
)
from tests.conftest import FakePool

SETTINGS = Settings(database_url="postgresql://unused")

TOKEN = "wersja-po-imporcie"
TILE_PATH = f"/api/tiles/buildings/{POLYGON_MIN_ZOOM}/9000/5500.mvt"
TILE_ETAG = tile_etag(TOKEN, POLYGON_MIN_ZOOM, 9000, 5500)


class FixedVersion:
    """Atrapa licznika wersji: oddaje podany token, nie dotykajac puli.

    Dzieki temu testy trasy moga sprawdzic, ze odpowiedz 304 nie wykonuje ZADNEGO zapytania —
    prawdziwy DataVersion czytalby token z tej samej atrapy puli i zamazywalby ten pomiar.
    """

    def __init__(self, value: str | None) -> None:
        self.value = value
        self.reads = 0

    async def token(self, _pool: Any, _timeout: float) -> str | None:
        self.reads += 1
        return self.value


def client_with(pool: FakePool, token: str | None = TOKEN) -> TestClient:
    app = create_app(SETTINGS, pool_factory=lambda _settings: pool)
    app.state.data_version = FixedVersion(token)
    return TestClient(app)


def test_close_zoom_serves_building_outlines() -> None:
    assert tile_sql(POLYGON_MIN_ZOOM) is POLYGON_TILE


def test_middle_zoom_serves_the_density_grid() -> None:
    assert tile_sql(POLYGON_MIN_ZOOM - 1) is DENSITY_TILE
    assert tile_sql(DENSITY_MIN_ZOOM) is DENSITY_TILE


def test_far_zoom_serves_nothing() -> None:
    assert tile_sql(DENSITY_MIN_ZOOM - 1) is None


def test_the_zoom_thresholds_did_not_move() -> None:
    # Siatka gestosci zastapila centroidy w tym samym zakresie zoomow: od 14 obrysy, 8-13 gestosc.
    # Prog w kodzie jest zdublowany w podpowiedzi na mapie, wiec jego zmiana nie jest szczegolem.
    assert (DENSITY_MIN_ZOOM, POLYGON_MIN_ZOOM) == (8, 14)


def test_the_polygon_tile_carries_osm_id_as_the_feature_identifier() -> None:
    """Identyfikatorem obiektu jest osm_id: klucz z sekwencji nie przezywa ponownego importu, wiec
    kafel z cache przegladarki wskazywal budynki, ktorych w bazie juz nie ma."""
    assert f"b.osm_id::bigint AS {FEATURE_ID}" in POLYGON_TILE
    assert "b.id" not in POLYGON_TILE  # wewnetrzny klucz nie ma prawa wyjsc na kafel


def test_the_feature_identifier_is_integer_and_named_the_way_st_asmvt_is_asked() -> None:
    """Dwa ciche sposoby, zeby kafel stracil identyfikatory obiektow: kolumna niecalkowita
    (PostGIS traktuje ja wtedy jako zwykly atrybut) albo inna nazwa kolumny niz podana
    w ST_AsMVT. Oba konczyly by sie kaflem, ktory wyglada dobrze, a nie da sie w niego kliknac."""
    assert f"::bigint AS {FEATURE_ID}" in POLYGON_TILE
    assert f"'geom', '{FEATURE_ID}')" in POLYGON_TILE


def test_the_polygon_tile_still_sends_untouched_building_outlines() -> None:
    """Zmiana dotyczy wylacznie oddalonej mapy. Kafel obrysow ma zostac dokladnie taki, jaki byl:
    warstwa `buildings`, atrybuty `listed` i `area_m2`, bez sladu agregacji."""
    assert f"'{POLYGON_LAYER}', 4096, 'geom', '{FEATURE_ID}'" in POLYGON_TILE
    assert "(b.registry_matches > 0) AS listed" in POLYGON_TILE
    assert "round(b.area_m2::numeric)::int AS area_m2" in POLYGON_TILE
    assert "ST_SnapToGrid" not in POLYGON_TILE
    assert "GROUP BY" not in POLYGON_TILE


def test_the_density_tile_aggregates_in_postgis_instead_of_sending_centroids() -> None:
    """Sedno zmiany: z oddalonej mapy leci siatka gestosci, a nie 319 869 centroidow.

    Bez agregacji kafel z8 wazyl 815 371 bajtow i heatmape musialaby policzyc przegladarka
    ze 150 tysiecy punktow — PostGIS robi to raz i oddaje gotowa wage komorki."""
    assert "ST_SnapToGrid" in DENSITY_TILE
    assert "GROUP BY" in DENSITY_TILE
    assert f'count(*)::int AS "{DENSITY_COUNT}"' in DENSITY_TILE
    assert "b.registry_matches > 0" in DENSITY_TILE  # liczymy zgloszone, a nie wszystkie budynki


def test_the_density_layer_has_a_new_name_so_the_old_frontend_cannot_misread_it() -> None:
    """Nazwa warstwy zmieniona z `listed` celowo: w kaflu nie ma juz budynkow, tylko komorki
    siatki. Pod stara nazwa stary frontend kliknalby w komorke i zapytal o budynek o numerze,
    ktorego nie ma."""
    assert DENSITY_LAYER == "listed_density"
    assert f"ST_AsMVT(feature.*, '{DENSITY_LAYER}', 4096, 'geom')" in DENSITY_TILE
    assert "'listed', 4096" not in DENSITY_TILE


def test_the_density_cell_carries_only_the_count() -> None:
    # `count` to waga heatmapy po stronie frontendu, wiec nazwa atrybutu jest czescia kontraktu.
    assert DENSITY_COUNT == "count"
    assert f'cell."{DENSITY_COUNT}"' in DENSITY_TILE


def test_the_density_features_have_no_identifier() -> None:
    """Komorka siatki nie jest budynkiem, wiec nie ma czego adresowac. Identyfikator w tej warstwie
    zaprosilby frontend do zapytania /api/buildings/{id} o obiekt, ktory nie istnieje — dlatego
    ST_AsMVT jest tu wolany BEZ piatego argumentu."""
    assert f"'geom', '{FEATURE_ID}')" not in DENSITY_TILE
    assert "osm_id" not in DENSITY_TILE
    assert f"AS {FEATURE_ID}" not in DENSITY_TILE


def test_the_density_grid_is_glued_to_the_tile_grid() -> None:
    """Rozmiar komorki liczony z szerokosci TEGO kafla, wiec dzieli ja bez reszty i granice komorek
    pokrywaja sie z granicami kafla. Siatka zaczepiona gdziekolwiek indziej dawalaby komorki lezace
    na dwoch kaflach naraz — czyli szwy i podwojne liczenie na granicach."""
    assert f"(ST_XMax(bounds.mercator) - ST_XMin(bounds.mercator)) / {DENSITY_GRID} AS cell_m" in DENSITY_TILE
    assert "ST_Transform(b.centroid, 3857)" in DENSITY_TILE  # siatka metryczna, a nie stopniowa


def test_the_density_grid_snaps_to_cell_centres_not_corners() -> None:
    """ST_SnapToGrid zaokragla do najblizszego wezla, wiec siatke zaczepiamy o POL komorki i wezel
    wypada w srodku komorki. Bez tego przesuniecia cala gestosc pojechalaby o pol komorki na
    polnocny zachod, a przy krawedzi kafla wyszlaby poza jego zakres."""
    assert "grid.corner_x + grid.cell_m / 2" in DENSITY_TILE
    assert "grid.corner_y + grid.cell_m / 2" in DENSITY_TILE


def test_the_density_tile_clips_its_input_exactly_and_from_one_side() -> None:
    """Krawedzie kafli. `&&` porownuje obwiednie zapamietane w float4 i zaokraglone na zewnatrz,
    wiec wpuszcza punkty tuz zza krawedzi: zmierzone kafle z8, z9 i z11 mialy przez to po jednym
    zgloszeniu za duzo, policzonym drugi raz takze u sasiada. Dlatego o przynaleznosci decyduje
    porownanie wspolrzednych, a zakres jest polotwarty — dwa sasiednie kafle maja wspolna krawedz
    co do bitu i domkniety z obu stron liczylby centroid na krawedzi dwa razy."""
    assert "ST_X(b.centroid) >= grid.lon_min AND ST_X(b.centroid) < grid.lon_max" in DENSITY_TILE
    assert "ST_Y(b.centroid) >= grid.lat_min AND ST_Y(b.centroid) < grid.lat_max" in DENSITY_TILE
    assert "b.centroid && grid.wgs84" in DENSITY_TILE  # zostaje dla indeksu GiST, nie dla wyniku


def test_the_cell_lands_on_a_whole_mvt_coordinate() -> None:
    """Kafel ma 4096 jednostek na bok i wspolrzedne w MVT sa calkowite. Gdyby DENSITY_GRID nie
    dzielilo 4096, srodki komorek zaokraglaloby raz w dol, raz w gore i siatka bylaby nierowna."""
    assert 4096 % DENSITY_GRID == 0
    assert (4096 // DENSITY_GRID) % 2 == 0  # pol komorki tez musi byc calkowite


def test_grid_rejects_coordinates_outside_the_zoom_level() -> None:
    assert within_grid(1, 1, 1)
    assert not within_grid(1, 2, 0)
    assert not within_grid(1, 0, -1)


def test_tile_endpoint_returns_the_vector_tile_with_an_etag_and_no_max_age() -> None:
    with client_with(FakePool(row=(b"tile-bytes",))) as client:
        response = client.get(TILE_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    # Kafel wolno trzymac, ale przed uzyciem trzeba dopytac — zadnego zgadywanego czasu zycia.
    assert response.headers["cache-control"] == "no-cache"
    assert "max-age" not in response.headers["cache-control"]
    assert response.headers["etag"] == TILE_ETAG
    assert response.content == b"tile-bytes"


def test_a_matching_if_none_match_gives_304_without_touching_the_pool() -> None:
    pool = FakePool(row=(b"tile-bytes",))

    with client_with(pool) as client:
        response = client.get(TILE_PATH, headers={"If-None-Match": str(TILE_ETAG)})

    assert response.status_code == 304
    assert response.content == b""
    assert "content-type" not in response.headers  # 304 nie ma prawa miec ciala ani typu
    assert response.headers["etag"] == TILE_ETAG
    assert pool.timeouts == []  # PostGIS nie byl odpytywany, wiec 304 jest tansze niz kafel


def test_a_stale_if_none_match_gives_the_new_tile() -> None:
    stale = tile_etag("wersja-przed-importem", POLYGON_MIN_ZOOM, 9000, 5500)
    pool = FakePool(row=(b"tile-bytes",))

    with client_with(pool) as client:
        response = client.get(TILE_PATH, headers={"If-None-Match": str(stale)})

    assert response.status_code == 200
    assert response.content == b"tile-bytes"
    assert response.headers["etag"] == TILE_ETAG
    assert pool.timeouts == [SETTINGS.database_timeout_s]


def test_the_etag_of_another_tile_does_not_confirm_this_one() -> None:
    other = tile_etag(TOKEN, POLYGON_MIN_ZOOM, 9001, 5500)

    with client_with(FakePool(row=(b"tile-bytes",))) as client:
        same = client.get(TILE_PATH).headers["etag"]
        response = client.get(TILE_PATH, headers={"If-None-Match": str(other)})

    assert same == TILE_ETAG
    assert other != TILE_ETAG
    assert response.status_code == 200


def test_a_new_data_version_changes_the_etag_of_the_same_tile() -> None:
    """Sedno naprawy: po imporcie ten sam kafel dostaje inny ETag, wiec stary nie jest juz swiezy."""
    with client_with(FakePool(row=(b"stare-id",)), token="przed-importem") as client:
        before = client.get(TILE_PATH)

    with client_with(FakePool(row=(b"nowe-id",)), token="po-imporcie") as client:
        after = client.get(TILE_PATH, headers={"If-None-Match": before.headers["etag"]})

    assert before.headers["etag"] != after.headers["etag"]
    assert after.status_code == 200
    assert after.content == b"nowe-id"


def test_an_etag_from_the_previous_tile_schema_gives_the_new_tile_not_304() -> None:
    """Kafel z poprzedniej wersji schematu (identyfikatory z sekwencji) lezy w cache przegladarki
    z niezmienionym tokenem danych. Bez skladnika schematu w ETagu dostalby 304 i klik w budynek
    znowu konczylby sie 404 — dlatego ten warunkowy GET musi dac 200."""
    from_schema_one = f'W/"v1-{TOKEN}-{POLYGON_MIN_ZOOM}-9000-5500"'

    with client_with(FakePool(row=(b"tile-bytes",))) as client:
        response = client.get(TILE_PATH, headers={"If-None-Match": from_schema_one})

    assert response.status_code == 200
    assert response.content == b"tile-bytes"
    assert response.headers["etag"] == TILE_ETAG
    assert response.headers["etag"] != from_schema_one


def test_a_tile_without_a_known_version_is_not_stored_at_all() -> None:
    # Brak wiersza wersji albo padnieta baza: kafel sie rysuje, ale bez ETagu nie wolno go trzymac,
    # bo nie bylo by czym uniewaznic go po imporcie.
    with client_with(FakePool(row=(b"tile-bytes",)), token=None) as client:
        response = client.get(TILE_PATH, headers={"If-None-Match": str(TILE_ETAG)})

    assert response.status_code == 200
    assert response.content == b"tile-bytes"
    assert "etag" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_empty_tile_is_204_instead_of_an_empty_200() -> None:
    with client_with(FakePool(row=(b"",))) as client:
        response = client.get(TILE_PATH)

    assert response.status_code == 204
    assert response.headers["etag"] == TILE_ETAG
    assert response.headers["cache-control"] == "no-cache"


def test_zoom_below_the_threshold_does_not_touch_the_database() -> None:
    pool = FakePool(row=(b"tile-bytes",))

    with client_with(pool) as client:
        response = client.get("/api/tiles/buildings/3/1/1.mvt")

    assert response.status_code == 204
    assert pool.timeouts == []
    # Pusty kafel ponizej progu zoomu wynika z kodu, nie z danych, wiec nie ma ETagu — ale i tu
    # przegladarka musi dopytac, bo prog zoomu moze sie zmienic razem z kodem.
    assert response.headers["cache-control"] == "no-cache"
    assert "etag" not in response.headers


def test_coordinates_outside_the_grid_are_rejected() -> None:
    with client_with(FakePool(row=(b"tile-bytes",))) as client:
        response = client.get("/api/tiles/buildings/2/9/0.mvt")

    assert response.status_code == 400


def test_a_dead_database_degrades_to_503_instead_of_breaking_the_map() -> None:
    with client_with(FakePool(error=OSError("connection refused"))) as client:
        response = client.get(TILE_PATH)

    assert response.status_code == 503
