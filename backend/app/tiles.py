"""Kafle wektorowe budynkow.

Przy 2,58 mln poligonow nie da sie wyslac do przegladarki GeoJSON-a calego wojewodztwa, wiec
PostGIS tnie geometrie na kafle przez ST_AsMVT. Zakres zoomu decyduje, co w kaflu jest:

* od POLYGON_MIN_ZOOM — obrysy budynkow, bo dopiero wtedy jeden budynek ma sensowny rozmiar,
* od DENSITY_MIN_ZOOM do POLYGON_MIN_ZOOM - 1 — SIATKA GESTOSCI zgloszen: jeden punkt na komorke
  siatki z liczba budynkow zgloszonych w rejestrze, bo z poziomu wojewodztwa liczy sie skupisko,
  a nie pojedynczy budynek,
* nizej — nic; kafel z milionem obiektow nikomu nie pomaga.

Kafel gestosci zastapil kafel surowych centroidow zgloszonych budynkow (warstwa `listed`). Powod
jest zmierzony: w rejestrze jest 319 869 zgloszonych budynkow i kafel z8 niosl 815 371 bajtow przez
1,1 s, a przegladarka miala z tego zrobic heatmape, czyli i tak policzyc gestosc — tyle ze na
150 tysiacach punktow, w jednym watku JS. Agregacja w PostGIS-ie oddaje gotowa wage komorki.

Identyfikatorem obiektu w kaflu obrysow jest `osm_id`, a nie klucz `id` z sekwencji: klik w budynek
wysyla te liczbe do `/api/buildings/{id}`, a sekwencja przezywa TRUNCATE, wiec po ponownym imporcie
stare kafle w cache przegladarki wskazywalyby nieistniejace budynki (pulapki 21 i 22 w AGENTS.md).
Obiekty warstwy gestosci identyfikatora NIE MAJA i miec nie moga: komorka siatki nie jest budynkiem,
wiec nie ma czego adresowac, a identyfikator wzialby sie tam tylko po to, zeby frontend mogl o niego
zapytac i dostac 404.

Kazda zmiana tresci albo znaczenia kafla (tu: inna nazwa warstwy, inne obiekty, inne atrybuty) idzie
razem z podbiciem TILE_SCHEMA_VERSION w app/dataversion.py, bez ktorego przegladarka potwierdzilaby
swiezosc kafla, ktory lezy u niej w cache, i heatmapa nie pojawilaby sie do wygasniecia tego cache'a.
"""

POLYGON_MIN_ZOOM = 14
DENSITY_MIN_ZOOM = 8
MAX_ZOOM = 22

POLYGON_LAYER = "buildings"

# Nazwa warstwy zmieniona z `listed` swiadomie: to juz nie sa budynki, tylko komorki siatki. Stara
# nazwa przezylaby zmiane tresci po cichu i stary frontend kliknalby w komorke jak w budynek.
DENSITY_LAYER = "listed_density"

# Jedyny atrybut warstwy gestosci: ile zgloszonych budynkow ma centroid w tej komorce. To jest waga
# heatmapy, wiec nazwa jest czescia kontraktu z frontendem.
DENSITY_COUNT = "count"

# Ile komorek na bok kafla. Rozmiar komorki to szerokosc kafla / DENSITY_GRID, wiec komorka ma stale
# 4096 / DENSITY_GRID = 64 jednostki MVT na kazdym zoomie: na ekranie to zawsze ~4 piksele, zmienia
# sie tylko obszar, ktory komorka pokrywa (na z8 ~1,5 km w terenie). Sufitem wagi kafla jest
# DENSITY_GRID^2 = 4096 obiektow i 64 wystarczylo: najciezszy kafel z8 zszedl z 815 371 na 15 882
# bajty w 1 009 komorkach. Gestsza siatka (128) dalaby komorke ~2 pikseli, czyli grubo ponizej
# promienia plamy heatmapy — przegladarka i tak by je zlala, a kafel moglby urosnac czterokrotnie.
DENSITY_GRID = 64

# Nazwa kolumny, ktora ST_AsMVT zamienia w identyfikator obiektu (piaty argument wywolania w kaflu
# obrysow — warstwa gestosci identyfikatorow nie ma). Jedna stala w obu miejscach zapytania, bo
# literowka nie jest bledem: PostGIS po cichu oddaje kafel bez identyfikatorow obiektow, a kolumne
# dokleja jako zwykly atrybut.
FEATURE_ID = "id"

# Kolumna identyfikatora MUSI byc calkowita. ST_AsMVT bierze pierwsza kolumne o tej nazwie w typie
# smallint/integer/bigint; `osm_id` jest kolumna `text`, wiec bez rzutowania zostalby zignorowany
# jako identyfikator i wyladowal jako zwykly atrybut - kafel wygladalby poprawnie, a klik w budynek
# przestalby dzialac. `bigint` miesci sie w uint64 formatu MVT, a wszystkie osm_id sa dodatnie.
_FEATURE_ID_COLUMN = f"b.osm_id::bigint AS {FEATURE_ID}"

_BOUNDS = """
WITH bounds AS (
    SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS mercator,
           ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84
)
"""

POLYGON_TILE = f"""
{_BOUNDS}, feature AS (
    SELECT {_FEATURE_ID_COLUMN},
           (b.registry_matches > 0) AS listed,
           round(b.area_m2::numeric)::int AS area_m2,
           ST_AsMVTGeom(ST_Transform(b.geom, 3857), bounds.mercator, 4096, 64, true) AS geom
    FROM osm_buildings b, bounds
    WHERE b.geom && bounds.wgs84
)
SELECT ST_AsMVT(feature.*, '{POLYGON_LAYER}', 4096, 'geom', '{FEATURE_ID}')
FROM feature WHERE geom IS NOT NULL
"""

# Siatka gestosci w EPSG:3857, przyklejona do siatki kafla: rozmiar komorki liczymy z szerokosci
# TEGO kafla (ST_XMax - ST_XMin), wiec dzieli ja bez reszty, a poczatek siatki bierzemy z jego
# rogu — komorki nie „plywaja" przy przesuwaniu mapy i nie zaleza od tego, ktory kafel je policzyl.
#
# ST_SnapToGrid ZAOKRAGLA do najblizszego wezla, a nie obcina, wiec siatke zaczepiamy o POL komorki
# i wezel wypada dokladnie w SRODKU komorki. Srodek, nie rog: rog przesunalby cala gestosc o pol
# komorki na polnocny zachod. Przy okazji zaden srodek nie wychodzi poza kafel — lezy co najmniej
# pol komorki od jego krawedzi — wiec bufor ST_AsMVTGeom nie ma tu nic do roboty.
#
# KRAWEDZIE KAFLI, czyli dlaczego zadne zgloszenie nie ginie i zadne nie liczy sie dwa razy:
# 1. Komorki nie leza na dwoch kaflach naraz, bo ich granice pokrywaja sie z granicami kafla.
#    Siatka zaczepiona gdziekolwiek indziej dawalaby przy kazdej granicy komorki policzone po
#    polowie w dwoch kaflach — czyli szwy w heatmapie.
# 2. Wejscie jest przyciete do zakresu kafla PRZED agregacja, i to przyciecie musi byc dokladne.
#    Sam operator `&&` nie wystarcza: porownuje obwiednie zapamietane w float4, zaokraglone na
#    zewnatrz, wiec wpuszcza punkty lezace tuz za krawedzia. Zmierzone na prawdziwych danych —
#    kafle z8, z9 i z11 mialy przez to po JEDNYM zgloszeniu za duzo, a ten sam budynek liczyl sie
#    drugi raz w sasiednim kaflu. `&&` zostaje wylacznie po to, zeby zapytanie szlo po indeksie
#    GiST, a o przynaleznosci decyduje porownanie wspolrzednych.
# 3. Zakres jest POLOTWARTY: [min, max). Sasiednie kafle maja wspolna krawedz co do bitu (ta sama
#    wartosc wychodzi z ST_TileEnvelope po obu stronach), wiec zakres domkniety z dwoch stron
#    liczylby centroid lezacy dokladnie na krawedzi w obu kaflach naraz. Zachodnia i poludniowa
#    krawedz nalezy do kafla, wschodnia i polnocna do sasiada — plaszczyzna dzieli sie bez reszty.
#
# Warstwa nie dostaje piatego argumentu ST_AsMVT, czyli obiekty nie maja identyfikatorow: komorka
# nie jest budynkiem i nie ma pod czym jej szukac w /api/buildings/{id}.
DENSITY_TILE = f"""
{_BOUNDS}, grid AS (
    SELECT bounds.mercator,
           bounds.wgs84,
           ST_XMin(bounds.wgs84) AS lon_min,
           ST_XMax(bounds.wgs84) AS lon_max,
           ST_YMin(bounds.wgs84) AS lat_min,
           ST_YMax(bounds.wgs84) AS lat_max,
           (ST_XMax(bounds.mercator) - ST_XMin(bounds.mercator)) / {DENSITY_GRID} AS cell_m,
           ST_XMin(bounds.mercator) AS corner_x,
           ST_YMin(bounds.mercator) AS corner_y
    FROM bounds
), cell AS (
    SELECT ST_SnapToGrid(
               ST_Transform(b.centroid, 3857),
               grid.corner_x + grid.cell_m / 2,
               grid.corner_y + grid.cell_m / 2,
               grid.cell_m,
               grid.cell_m
           ) AS center,
           count(*)::int AS "{DENSITY_COUNT}"
    FROM osm_buildings b, grid
    WHERE b.registry_matches > 0
      AND b.centroid && grid.wgs84
      AND ST_X(b.centroid) >= grid.lon_min AND ST_X(b.centroid) < grid.lon_max
      AND ST_Y(b.centroid) >= grid.lat_min AND ST_Y(b.centroid) < grid.lat_max
    GROUP BY 1
), feature AS (
    SELECT cell."{DENSITY_COUNT}",
           ST_AsMVTGeom(cell.center, grid.mercator, 4096, 64, true) AS geom
    FROM cell, grid
)
SELECT ST_AsMVT(feature.*, '{DENSITY_LAYER}', 4096, 'geom')
FROM feature WHERE geom IS NOT NULL
"""


def tile_sql(zoom: int) -> str | None:
    """Zapytanie dla tego zoomu albo None, gdy kafel ma byc pusty."""
    if zoom >= POLYGON_MIN_ZOOM:
        return POLYGON_TILE
    if zoom >= DENSITY_MIN_ZOOM:
        return DENSITY_TILE
    return None


def within_grid(zoom: int, x: int, y: int) -> bool:
    if not 0 <= zoom <= MAX_ZOOM:
        return False
    side = 1 << zoom
    return 0 <= x < side and 0 <= y < side
