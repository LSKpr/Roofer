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

import asyncio
import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

import httpx

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
#
# Identyfikatorem jest `osm_id`, nie klucz z sekwencji — i to jest dla atrapy ulepszenie, nie tylko
# spojnosc z reszta API: werdykt liczony ze skrotu identyfikatora przestaje sie zmieniac po kazdym
# imporcie, bo `osm_id` jest trwaly. Wczesniej ten sam budynek po ponownym imporcie dostawal nowy
# klucz i nowa „ocene", co na demo wygladalo jak losowanie. Parametr rzutujemy na text, a nie
# kolumne na bigint, bo tylko wtedy dziala indeks osm_buildings_osm_id_key (migracja 006).
BUILDING_SHAPE_SQL = """
SELECT b.osm_id::bigint                     AS id,
       round(b.area_m2::numeric, 1)::float8 AS area_m2,
       ST_X(b.centroid)                     AS lng,
       ST_Y(b.centroid)                     AS lat,
       ST_XMin(b.geom)                      AS west,
       ST_YMin(b.geom)                      AS south,
       ST_XMax(b.geom)                      AS east,
       ST_YMax(b.geom)                      AS north
FROM osm_buildings b
WHERE b.osm_id = %(id)s::text
"""

# Noty sa tekstem, ktory czyta urzednik w karcie budynku, wiec pisane sa poprawna polszczyzna
# z diakrytykami. Zasada „bez znakow diakrytycznych" dotyczy komentarzy i identyfikatorow w kodzie,
# a nie komunikatow — te bez ogonkow wygladaly w interfejsie na usterke.
MOCK_SUSPECTED_NOTE = (
    "Wynik demonstracyjny, bez modelu ML — liczba pochodzi ze skrótu identyfikatora budynku, "
    "nie ze zdjęcia. Docelowy model rozpoznaje faliste, szare pokrycie typowe dla eternitu, "
    "a nie obecność azbestu w dachu."
)

MOCK_UNLIKELY_NOTE = (
    "Wynik demonstracyjny, bez modelu ML — liczba pochodzi ze skrótu identyfikatora budynku, "
    "nie ze zdjęcia. Niska ocena niczego nie dowodzi: docelowy model patrzy tylko na to, czy "
    "pokrycie wygląda na faliste i szare jak eternit."
)

MOCK_UNKNOWN_NOTE = (
    "Wynik demonstracyjny, bez modelu ML — dla tego budynku atrapa nie oddaje oceny, tak jak "
    "docelowy model przy braku zdjęcia okolicy. Brak oceny to nie to samo co ocena zero."
)

UNAVAILABLE_NOTE = (
    "Ocena pokrycia dachu nie jest skonfigurowana, więc nie ma żadnego wyniku — a brak wyniku to "
    "nie to samo co ocena zero. Model, gdy się pojawi, będzie rozpoznawał faliste, szare pokrycie "
    "typowe dla eternitu, a nie obecność azbestu."
)

PROVIDER_ERROR_NOTE = (
    "Serwis oceny pokrycia dachu nie odpowiedział, więc nie ma wyniku — brak wyniku to nie to "
    "samo co ocena zero. Spróbuj ponownie za chwilę."
)


@dataclass(frozen=True)
class BuildingShape:
    """Tyle o budynku, ile dostawca potrzebuje — i ani slowa z rejestru.

    `bbox` jest tu dlatego, ze przyszle API modelu przyjmuje prostokat, a nie identyfikator:
    dostawca HTTP wezmie ten bbox (ewentualnie rozszerzony marginesem), dostanie poligony dachow
    z okolicy i dopiero wtedy wybierze ten, ktory pokrywa nasz budynek.
    """

    id: int
    """`osm_id` budynku — trwaly miedzy importami, wiec atrapa liczy z niego stabilny werdykt."""
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
    """Liczba z przedzialu [0, 1) wyznaczona ze skrotu identyfikatora budynku, czyli `osm_id`.

    `random` bez ziarna migalby przy kazdym kliknieciu i demo pokazywaloby inna „ocene" za kazdym
    razem, wiec bierzemy pierwsze 8 bajtow SHA-256 z osolonego identyfikatora. Ten sam budynek
    zawsze dostaje te sama liczbe, a rozne budynki praktycznie nigdy tej samej.

    Odkad identyfikatorem jest `osm_id`, „ten sam budynek" znaczy takze „po ponownym imporcie":
    klucz z sekwencji sie wtedy przesuwal i werdykt atrapy dla tego samego dachu sie zmienial.
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


async def read_building_shape(pool: Any, osm_id: int, timeout: float) -> BuildingShape | None:
    async with pool.connection(timeout=timeout) as connection:
        cursor = await connection.execute(BUILDING_SHAPE_SQL, {"id": osm_id})
        row = await cursor.fetchone()
    return shape_from_row(row)


def unavailable_analysis(note: str = UNAVAILABLE_NOTE) -> RoofAnalysis:
    """Jedyna uczciwa odpowiedz, gdy nikt nie skonfigurowal modelu albo serwis nie odpowiada."""
    return RoofAnalysis(source="unavailable", verdict="unknown", probability=None, model_name=None, note=note)


def mock_analysis(building_id: int) -> RoofAnalysis:
    """Deterministyczna atrapa: wejsciem jest wylacznie identyfikator budynku, czyli `osm_id`.

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


ANALYZE_PATH = "/v1/analyze"

# Statusy zwracane przez API modelu. Tylko `ok` niesie liczbe; reszta to jawne „nie wiemy",
# i wlasnie dlatego ten model da sie podlaczyc bez lamania naszej zasady, ze brak wyniku to None.
MODEL_STATUS_OK = "ok"

STATUS_NOTES = {
    "low_quality": "zdjęcie nie przeszło kontroli jakości",
    "imagery_error": "nie udało się pobrać zdjęcia okolicy",
    "geometry_error": "nie udało się wyznaczyć punktu wewnątrz dachu",
}

# Model patrzy na INNE zdjecie niz to, ktore uzytkownik widzi w karcie: on na Google Satellite
# z zoomu 20, my pokazujemy ortofotomape GUGiK. Bez tego zdania ktos porownalby ocene z kadrem
# obok i wyciagnal wniosek z dwoch roznych zrodel. Skutecznosc podana przez autora modelu.
MODEL_IMAGERY_NOTE = (
    "Ocena z jednego zdjęcia satelitarnego Google (zoom 20), a nie z ortofotomapy GUGiK pokazanej "
    "w tej karcie — model i zdjęcie obok to dwa różne źródła. Model rozpoznaje wygląd pokrycia, "
    "nie materiał: autor podaje skuteczność 77% i wykrywalność azbestu 63%, więc wynik jest "
    "wskazówką do oględzin, a nie rozstrzygnięciem."
)

MODEL_NO_RESULT_NOTE = (
    "Model nie ocenił tego dachu ({powod}), więc nie ma wyniku — a brak wyniku to nie to samo "
    "co ocena zero. Reszta karty pozostaje aktualna."
)

MODEL_MISSING_NOTE = (
    "Serwis oceny nie zwrócił tego budynku, więc nie ma wyniku. Brak wyniku to nie to samo co ocena zero."
)

MODEL_BUSY_NOTE = (
    "Serwis oceny jest zajęty i poprosił o przerwę ({seconds} s), więc nie ma teraz wyniku. "
    "Spróbuj ponownie za chwilę — brak wyniku to nie to samo co ocena zero."
)


def analyze_request(building: BuildingShape) -> dict[str, dict[str, float]]:
    """Cialo zapytania: prostokat budynku w WGS84, naroznik SW i NE — tak jak chce API modelu."""
    west, south, east, north = building.bbox
    return {
        "south_west": {"longitude": west, "latitude": south},
        "north_east": {"longitude": east, "latitude": north},
    }


def find_feature(payload: dict[str, Any], osm_id: int) -> dict[str, Any] | None:
    """Nasz budynek w odpowiedzi, po `source_id`.

    Dopasowujemy po identyfikatorze OSM, a nie geometrycznie, bo serwis korzysta z tego samego
    snapshotu co my (2 585 219 budynkow, sprawdzone w jego /health) i sam oddaje `source_id`.
    To jest dokladniejsze niz liczenie przekrycia: w prostokacie jednego budynku siedza tez
    sasiednie dachy — przy pierwszym zapytaniu na zywo obok bloku wyszedl garaz sasiada.
    `building_id` i `id` sa ich wewnetrznymi kluczami i nie wolno ich do tego uzywac.
    """
    wanted = str(osm_id)
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        if str(properties.get("source_id")) == wanted:
            return properties
    return None


def analysis_from_properties(properties: dict[str, Any], model_id: str | None) -> RoofAnalysis:
    """Wlasciwosci obiektu z API modelu na nasza ocene.

    Brak `model_id` konczy sie „nie wiemy", a nie wynikiem bez nazwy modelu: `RoofAnalysis` wymaga
    nazwy przy `source="model"`, a wymyslenie jej byloby podaniem atrapy za model.
    """
    if not model_id:
        return unavailable_analysis(MODEL_MISSING_NOTE)

    status = str(properties.get("status") or "")
    probability = properties.get("asbestos_probability")
    if status != MODEL_STATUS_OK or probability is None:
        reasons = properties.get("reasons") or []
        detail = ", ".join(str(reason) for reason in reasons) if reasons else STATUS_NOTES.get(status, status or "brak")
        return RoofAnalysis(
            source="model",
            verdict="unknown",
            probability=None,
            model_name=model_id,
            note=MODEL_NO_RESULT_NOTE.format(powod=detail) + " " + MODEL_IMAGERY_NOTE,
        )

    value = round(float(probability), 4)
    return RoofAnalysis(
        source="model",
        verdict="suspected" if value >= SUSPECTED_THRESHOLD else "unlikely",
        probability=value,
        model_name=model_id,
        note=MODEL_IMAGERY_NOTE,
    )


class HttpModelProvider:
    """Ocena z zewnetrznego API modelu (`POST /v1/analyze`).

    Trzy ograniczenia tamtej instancji wymuszaja ksztalt tej klasy: **10 zapytan na minute**,
    **jedno naraz** i kilka sekund na odpowiedz. Karta budynku pyta o ocene przy kazdym
    kliknieciu, wiec bez cache'u i ogranicznika jedenaste klikniecie w minucie dostaloby 429.
    Cache trzyma wynik po `osm_id`: ocena tego samego dachu z tego samego zdjecia sie nie zmienia,
    wiec pamietanie jej niczego nie falszuje.

    Token nie trafia nigdzie poza naglowek zadania — nie ma go w notach, bledach ani w `repr`.
    """

    source: Source = "model"

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_s: float = 60.0,
        cache_ttl_s: float = 3600.0,
        min_interval_s: float = 6.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout_s = timeout_s
        self.cache_ttl_s = cache_ttl_s
        self.min_interval_s = min_interval_s
        self._transport = transport
        self._clock = clock
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        # Jedno zapytanie naraz, bo tamta instancja i tak odrzuca rownolegle (429 BUSY).
        self._request_lock = asyncio.Lock()
        self._next_allowed_s = 0.0
        self._cache: dict[int, tuple[float, RoofAnalysis]] = {}

    def __repr__(self) -> str:  # token nie ma prawa wyciec do logu ani do tracebacku
        return f"HttpModelProvider(base_url={self.base_url!r})"

    async def client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=self.timeout_s,
                    headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                    transport=self._transport,
                )
        return self._client

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def cached(self, osm_id: int) -> RoofAnalysis | None:
        entry = self._cache.get(osm_id)
        if entry is None:
            return None
        expires_at, analysis = entry
        if expires_at <= self._clock():
            del self._cache[osm_id]
            return None
        return analysis

    async def analyze(self, building: BuildingShape) -> RoofAnalysis:
        hit = self.cached(building.id)
        if hit is not None:
            return hit

        try:
            response = await self._post(analyze_request(building))
        except httpx.HTTPError:
            # Padniety serwis nie moze zabrac karty budynku ani udawac wyniku.
            return unavailable_analysis(PROVIDER_ERROR_NOTE)

        if response.status_code == 429:
            return unavailable_analysis(MODEL_BUSY_NOTE.format(seconds=response.headers.get("Retry-After", "kilka")))
        if response.status_code != 200:
            return unavailable_analysis(PROVIDER_ERROR_NOTE)

        try:
            payload = response.json()
        except ValueError:
            return unavailable_analysis(PROVIDER_ERROR_NOTE)

        properties = find_feature(payload, building.id)
        if properties is None:
            return unavailable_analysis(MODEL_MISSING_NOTE)

        model_id = (payload.get("meta") or {}).get("model_id")
        analysis = analysis_from_properties(properties, model_id)
        # Zapamietujemy takze „nie wiemy" od modelu: powtorne pytanie dostaloby ten sam werdykt,
        # a limit 10 zapytan na minute jest wspolny dla calej instancji.
        self._cache[building.id] = (self._clock() + self.cache_ttl_s, analysis)
        return analysis

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        """Zapytanie pod blokada: rezerwujemy okno, spimy poza nia, dopiero potem pytamy."""
        client = await self.client()
        async with self._request_lock:
            delay = max(0.0, self._next_allowed_s - self._clock())
            if delay > 0.0:
                await asyncio.sleep(delay)
            self._next_allowed_s = self._clock() + self.min_interval_s
            return await client.post(f"{self.base_url}{ANALYZE_PATH}", json=body)


# Nazwy z konfiguracji (`prediction_provider`) na klasy dostawcow.
PROVIDERS: dict[str, type] = {"mock": MockProvider, "none": UnavailableProvider, "model": HttpModelProvider}
PROVIDER_NAMES = tuple(PROVIDERS)


def build_provider(name: str, settings: Any | None = None) -> RoofAnalysisProvider:
    """Nazwa z konfiguracji na dostawce. Literowka nie wywala serwera, tylko konczy sie „nie wiemy".

    Swiadomie nie rzucamy bledem: nierozpoznana nazwa nie moze skutkowac tym, ze pokazemy
    jakikolwiek wynik — brak konfiguracji i zla konfiguracja znacza dokladnie tyle samo.
    Tak samo `model` bez adresu albo bez tokenu: lepiej „nie wiemy" niz zapytanie, ktore i tak
    wroci 401.
    """
    key = name.strip().lower()
    if key == "model":
        url = str(getattr(settings, "prediction_api_url", "") or "")
        # Token jest SecretStr, zeby nie wyciekl przez repr Settings; tu potrzebna jest wartosc.
        raw_token = getattr(settings, "prediction_api_token", "")
        token = raw_token.get_secret_value() if hasattr(raw_token, "get_secret_value") else str(raw_token or "")
        if not url or not token:
            return UnavailableProvider()
        return HttpModelProvider(
            base_url=url,
            token=token,
            timeout_s=float(getattr(settings, "prediction_timeout_s", 60.0)),
            cache_ttl_s=float(getattr(settings, "prediction_cache_ttl_s", 3600.0)),
            min_interval_s=float(getattr(settings, "prediction_min_interval_s", 6.0)),
        )
    factory = PROVIDERS.get(key)
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
        provider = build_provider(app.state.settings.prediction_provider, app.state.settings)
        app.state.roof_provider = provider
    return provider
