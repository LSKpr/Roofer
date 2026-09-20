"""Gniazdo na ocene pokrycia dachu: dzisiaj jawnie oznaczona atrapa, docelowo model ML.

Co wiadomo o przyszlym modelu (stan na P5): wlasciciel projektu dostanie od wspolpracownika API,
do ktorego **wysyla sie narozniki prostokata (bbox), a dostaje poligony wykrytych dachow razem
z pozycja na mapie**. Przyszly dostawca bedzie wiec musial:

1. odpytac tamten serwis o okolice budynku, czyli podac jego bbox (zwykle z marginesem),
2. przeciac zwrocone poligony z geometria tego budynku (`ST_Intersects`) i wziac ten, ktory
   pokrywa najwiekszy udzial jego powierzchni — serwis oddaje dachy z okolicy, nie „nasz" dach,
3. przelozyc pewnosc modelu na `probability` i `verdict`.

Dlatego dostawca dostaje `BuildingShape` (id, centroid, bbox, powierzchnia), a nie sam
identyfikator: dopisanie dostawcy HTTP nie bedzie wymagalo zmiany trasy ani kontraktu odpowiedzi.
Samego dostawcy HTTP tutaj nie ma, bo kontrakt tamtego API nie jest jeszcze znany — zgadywanie go
teraz skonczyloby sie przepisywaniem.

Trzy zasady, ktorych nie wolno tu zlamac:

* **Atrapa musi byc rozpoznawalna po odpowiedzi**, nie tylko w UI: `source="mock"`,
  `modelName=None` i `note`, ktora wprost mowi, ze to wynik demonstracyjny bez modelu. Atrapa
  nigdy nie podaje sie za `"model"`.
* **Atrapa nie zaglada do `registry_matches`** — w BUILDING_SHAPE_SQL nie ma tej kolumny i nie
  moze sie tam pojawic. Udawanie, ze niezalezna analiza zgadza sie ze zgloszeniem w rejestrze,
  byloby sfabrykowanym dowodem, a ten projekt istnieje wlasnie po to, zeby tego nie robic.
* **Brak wyniku to `probability=None`, nigdy 0.0.** Zero znaczy „sprawdzone i nie widac
  eternitu", a brak wyniku znaczy „nie wiemy" — ta sama zasada, co trzy stany statusu w rejestrze.
  Pilnuje jej `RoofAnalysis.__post_init__`, wiec zadny przyszly dostawca nie obejdzie tego przez
  nieuwage.

Model, gdy sie pojawi, ocenia **wyglad pokrycia** (faliste, szare plyty typowe dla eternitu),
a nie obecnosc azbestu w materiale — i tak musza brzmiec wszystkie komunikaty w tym pliku.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

Source = Literal["mock", "model", "unavailable"]
Verdict = Literal["suspected", "unlikely", "unknown"]

# Prog, od ktorego ocena liczy sie jako „podejrzane pokrycie". Jedno miejsce, zeby front i backend
# nie mialy dwoch roznych granic.
SUSPECTED_THRESHOLD = 0.5

# Czesc budynkow, dla ktorych atrapa nie oddaje oceny. Prawdziwy model tez nie odpowie na kazdy
# budynek (brak zdjecia okolicy, chmury, cien), a demo ma pokazywac ten trzeci stan, nie ukrywac go.
NO_RESULT_SHARE = 0.12

# Dwie sole daja z jednego identyfikatora dwie niezalezne liczby: „jaka ocena" i „czy ocena jest".
PROBABILITY_SALT = "roofer-mock-probability:"
COVERAGE_SALT = "roofer-mock-coverage:"

# Zapytanie dostawcy: tylko geometria budynku. Swiadomie NIE ma tu `registry_matches` ani niczego
# z rejestru — ocena pokrycia ma byc niezalezna od zgloszenia, inaczej „zgadza sie z rejestrem"
# znaczylo tylko „przepisalem rejestr". Pilnuje tego test w tests/test_prediction.py.
BUILDING_SHAPE_SQL = """
SELECT b.id,
       round(b.area_m2::numeric, 1)::float8 AS area_m2,
       ST_X(b.centroid)                     AS lng,
       ST_Y(b.centroid)                     AS lat,
       ST_XMin(b.geom)                      AS west,
       ST_YMin(b.geom)                      AS south,
       ST_XMax(b.geom)                      AS east,
       ST_YMax(b.geom)                      AS north
FROM osm_buildings b
WHERE b.id = %(id)s
"""

MOCK_SUSPECTED_NOTE = (
    "Wynik demonstracyjny, bez modelu ML — liczba pochodzi ze skrotu identyfikatora budynku, "
    "nie ze zdjecia. Docelowy model rozpoznaje faliste, szare pokrycie typowe dla eternitu, "
    "a nie obecnosc azbestu w dachu."
)

MOCK_UNLIKELY_NOTE = (
    "Wynik demonstracyjny, bez modelu ML — liczba pochodzi ze skrotu identyfikatora budynku, "
    "nie ze zdjecia. Niska ocena niczego nie dowodzi: docelowy model patrzy tylko na to, czy "
    "pokrycie wyglada na faliste i szare jak eternit."
)

MOCK_UNKNOWN_NOTE = (
    "Wynik demonstracyjny, bez modelu ML — dla tego budynku atrapa nie oddaje oceny, tak jak "
    "docelowy model przy braku zdjecia okolicy. Brak oceny to nie to samo co ocena zero."
)

UNAVAILABLE_NOTE = (
    "Ocena pokrycia dachu nie jest skonfigurowana, wiec nie ma zadnego wyniku — a brak wyniku to "
    "nie to samo co ocena zero. Model, gdy sie pojawi, bedzie rozpoznawal faliste, szare pokrycie "
    "typowe dla eternitu, a nie obecnosc azbestu."
)

PROVIDER_ERROR_NOTE = (
    "Serwis oceny pokrycia dachu nie odpowiedzial, wiec nie ma wyniku — brak wyniku to nie to "
    "samo co ocena zero. Sprobuj ponownie za chwile."
)


@dataclass(frozen=True)
class BuildingShape:
    """Tyle o budynku, ile dostawca potrzebuje — i ani slowa z rejestru.

    `bbox` jest tu dlatego, ze przyszle API modelu przyjmuje prostokat, a nie identyfikator:
    dostawca HTTP wezmie ten bbox (ewentualnie rozszerzony marginesem), dostanie poligony dachow
    z okolicy i dopiero wtedy wybierze ten, ktory pokrywa nasz budynek.
    """

    id: int
    lng: float
    lat: float
    west: float
    south: float
    east: float
    north: float
    area_m2: float | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Kolejnosc [west, south, east, north], czyli naroznik SW i pozniej NE — jak w geocode."""
        return (self.west, self.south, self.east, self.north)


@dataclass(frozen=True)
class RoofAnalysis:
    """Wynik oceny pokrycia. Konstruktor pilnuje, zeby odpowiedz nie klamala o swoim pochodzeniu."""

    source: Source
    verdict: Verdict
    probability: float | None
    model_name: str | None
    note: str

    def __post_init__(self) -> None:
        no_result = self.verdict == "unknown" or self.source == "unavailable"
        if self.source == "unavailable" and self.verdict != "unknown":
            raise ValueError("Brak dostawcy nie moze konczyc sie werdyktem innym niz 'unknown'.")
        if no_result and self.probability is not None:
            # Zero znaczy „sprawdzone i nie widac eternitu"; brak wyniku to None i tylko None.
            raise ValueError("Brak wyniku zapisujemy jako None, nigdy jako 0.0.")
        if not no_result and (self.probability is None or not 0.0 <= self.probability <= 1.0):
            raise ValueError("Werdykt 'suspected' albo 'unlikely' musi miec prawdopodobienstwo z zakresu 0-1.")
        if self.source == "mock" and self.model_name is not None:
            raise ValueError("Atrapa nie ma prawa podawac nazwy modelu — ma byc rozpoznawalna po odpowiedzi.")
        if self.source == "model" and not self.model_name:
            raise ValueError("Wynik oznaczony jako 'model' musi mowic, ktory model go wydal.")


@runtime_checkable
class RoofAnalysisProvider(Protocol):
    """Gniazdo: jedna metoda, ktora z geometrii budynku robi ocene pokrycia.

    Dostawca nie dostaje puli po lacza do bazy — ocena ma zalezec od budynku, nie od tego, co
    jeszcze da sie w bazie doczytac. Przyszly dostawca HTTP bedzie potrzebowal tylko `BuildingShape`
    i wlasnego klienta httpx, wiec trasa (app/routes/prediction.py) nie bedzie sie zmieniac.
    """

    source: Source

    async def analyze(self, building: BuildingShape) -> RoofAnalysis: ...


def stable_unit(building_id: int, salt: str) -> float:
    """Liczba z przedzialu [0, 1) wyznaczona ze skrotu identyfikatora.

    `random` bez ziarna migalby przy kazdym kliknieciu i demo pokazywaloby inna „ocene" za kazdym
    razem, wiec bierzemy pierwsze 8 bajtow SHA-256 z osolonego identyfikatora. Ten sam budynek
    zawsze dostaje te sama liczbe, a rozne budynki praktycznie nigdy tej samej.
    """
    digest = hashlib.sha256(f"{salt}{building_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def shape_from_row(row: Sequence[Any] | None) -> BuildingShape | None:
    """Wiersz z BUILDING_SHAPE_SQL na `BuildingShape`; brak wiersza to brak budynku, nie blad."""
    if row is None:
        return None
    building_id, area_m2, lng, lat, west, south, east, north = row[:8]
    return BuildingShape(
        id=int(building_id),
        lng=float(lng),
        lat=float(lat),
        west=float(west),
        south=float(south),
        east=float(east),
        north=float(north),
        area_m2=float(area_m2) if area_m2 is not None else None,
    )


async def read_building_shape(pool: Any, building_id: int, timeout: float) -> BuildingShape | None:
    async with pool.connection(timeout=timeout) as connection:
        cursor = await connection.execute(BUILDING_SHAPE_SQL, {"id": building_id})
        row = await cursor.fetchone()
    return shape_from_row(row)


def unavailable_analysis(note: str = UNAVAILABLE_NOTE) -> RoofAnalysis:
    """Jedyna uczciwa odpowiedz, gdy nikt nie skonfigurowal modelu albo serwis nie odpowiada."""
    return RoofAnalysis(source="unavailable", verdict="unknown", probability=None, model_name=None, note=note)


def mock_analysis(building_id: int) -> RoofAnalysis:
    """Deterministyczna atrapa: wejsciem jest wylacznie identyfikator budynku.

    Powierzchnia ani nic z rejestru tu nie wchodzi. Mniej wejsc to mniej okazji, zeby atrapa
    „przypadkiem" zgadzala sie ze zgloszeniem i zostala wzieta za potwierdzenie.
    """
    if stable_unit(building_id, COVERAGE_SALT) < NO_RESULT_SHARE:
        return RoofAnalysis(
            source="mock",
            verdict="unknown",
            probability=None,
            model_name=None,
            note=MOCK_UNKNOWN_NOTE,
        )
    probability = round(stable_unit(building_id, PROBABILITY_SALT), 4)
    suspected = probability >= SUSPECTED_THRESHOLD
    return RoofAnalysis(
        source="mock",
        verdict="suspected" if suspected else "unlikely",
        probability=probability,
        model_name=None,  # atrapa nie ma modelu i nie wolno jej udawac, ze ma
        note=MOCK_SUSPECTED_NOTE if suspected else MOCK_UNLIKELY_NOTE,
    )


class MockProvider:
    """Atrapa oznaczona w odpowiedzi: `source="mock"`, `modelName=None`, `note` o demonstracji."""

    source: Source = "mock"

    async def analyze(self, building: BuildingShape) -> RoofAnalysis:
        return mock_analysis(building.id)


class UnavailableProvider:
    """Dostawca na czasy, gdy nikt nic nie skonfigurowal: zawsze „nie wiemy", nigdy zero."""

    source: Source = "unavailable"

    async def analyze(self, building: BuildingShape) -> RoofAnalysis:
        return unavailable_analysis()


# Nazwy z konfiguracji (`prediction_provider`) na klasy dostawcow. Dostawce HTTP dopisze sie tu
# jedna linia, gdy kontrakt API bedzie znany.
PROVIDERS: dict[str, type] = {"mock": MockProvider, "none": UnavailableProvider}
PROVIDER_NAMES = tuple(PROVIDERS)


def build_provider(name: str) -> RoofAnalysisProvider:
    """Nazwa z konfiguracji na dostawce. Literowka nie wywala serwera, tylko konczy sie „nie wiemy".

    Swiadomie nie rzucamy bledem: nierozpoznana nazwa nie moze skutkowac tym, ze pokazemy
    jakikolwiek wynik — brak konfiguracji i zla konfiguracja znacza dokladnie tyle samo.
    """
    factory = PROVIDERS.get(name.strip().lower())
    if factory is None:
        return UnavailableProvider()
    provider: RoofAnalysisProvider = factory()
    return provider


def get_provider(app: Any) -> RoofAnalysisProvider:
    """Jeden dostawca na aplikacje, tworzony przy pierwszym zapytaniu.

    Stan siedzi w `app.state`, wiec test moze podstawic wlasnego dostawce (`app.state.roof_provider`)
    bez dotykania konfiguracji, a przyszly dostawca HTTP dostanie tu miejsce na wspolnego klienta.
    """
    provider: RoofAnalysisProvider | None = getattr(app.state, "roof_provider", None)
    if provider is None:
        provider = build_provider(app.state.settings.prediction_provider)
        app.state.roof_provider = provider
    return provider
