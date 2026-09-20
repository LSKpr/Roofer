"""Ortofotomapa GUGiK: kafle podkladu i wycinek dachu jednego budynku.

Ustalenia z GetCapabilities (pobrane 2026-09-20 z tej maszyny, oba adresy odpowiedzialy 200):

* protokol to **WMS 1.3.0**, nie WMTS — jest tylko GetMap z dowolnym bboksem,
* jedyna warstwa nazywa sie `Raster` (styl `default`), formaty m.in. `image/png`,
* StandardResolution wspiera `EPSG:3857` (obok 4326, 2180, 2176-2179, CRS:84),
* HighResolution ogloszil tylko CRS:84, 4326 i 2180, ale `EPSG:3857` przyjmuje i zwraca ten sam
  obraz co StandardResolution tam, gdzie ma pokrycie; poza miastami oddaje pusty kafel 1320 B,
  wiec **domyslnie uzywamy StandardResolution** — dziury w podkladzie sa gorsze niz mniejszy piksel,
* `MaxWidth`/`MaxHeight` to 4096, wiec limit 128-1024 px na wycinek jest bezpieczny.

Dlaczego EPSG:3857: MapLibre renderuje w Web Mercatorze, wiec kafel z WMS-a w 3857 pokrywa sie
z kaflem siatki XYZ piksel w piksel i nie trzeba nic przeskalowywac. Gdyby przyszlo uzyc 4326,
obraz w plate carree nie pasowalby do kafla merkatorowego (blad rosnie z szerokoscia geograficzna).
3857 jest tez odwzorowaniem wiernokatnym, wiec kwadratowy bbox wycinka dachu daje nieznieksztalcony
obraz, i nie trzeba wchodzic w EPSG:2180, ktory ma w WMS 1.3.0 os polnocna jako pierwsza.

Pulapka osi — swiadomy wybor: zostajemy na 1.3.0, bo tylko ta wersja jest ogloszona w Capabilities.
W 1.3.0 kolejnosc w BBOX zalezy od definicji ukladu: dla EPSG:3857 jest to easting,northing (tak jak
w 1.1.1), i to sprawdzilismy zapytaniem — bbox po zamianie osi zwraca pusty kafel 792 B. Dla
EPSG:4326 w 1.3.0 byloby lat,lon (tez sprawdzone), ale tego ukladu tutaj nie uzywamy.

Degradacja: GUGiK przy bledzie potrafi zwrocic `ServiceException` w XML z kodem **200** (sprawdzone:
zla nazwa warstwy oraz WIDTH=4097 daja `text/xml` i status 200). Dlatego kazda odpowiedz sprawdzamy
podwojnie — naglowek `Content-Type` ORAZ magiczne bajty PNG.

Atrybucja: `GUGIK_ATTRIBUTION` musi byc widoczna w UI. Regulamin uslugi (AccessConstraints
w Capabilities) wyklucza automatyczne pobieranie i kolekcjonowanie obrazow (harvesting), dlatego
proxy sciaga wylacznie kafle obszaru, ktory uzytkownik ma na ekranie, trzyma je w malym cache
w pamieci i ogranicza liczbe jednoczesnych zapytan. Zadnego masowego zasysania ani zapisu na dysk.
"""

import asyncio
from collections import OrderedDict
from typing import Any

import httpx

GUGIK_ATTRIBUTION = "Ortofotomapa: GUGiK / Geoportal.gov.pl"

WMS_VERSION = "1.3.0"
WMS_CRS = "EPSG:3857"
IMAGE_MEDIA_TYPE = "image/png"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Polowa obwodu rownika: krawedz swiata w EPSG:3857.
ORIGIN_SHIFT_M = 20037508.342789244
TILE_PIXELS = 256

ROOF_DEFAULT_SIZE = 384
ROOF_MIN_SIZE = 128
ROOF_MAX_SIZE = 1024
ROOF_MARGIN = 0.2
# Garaz 3x3 m bez marginesu dalby bbox mniejszy od piksela ortofoto; ponizej tego nie schodzimy.
ROOF_MIN_SPAN_M = 12.0

# Bbox budynku liczymy od razu w 3857, bo w tym ukladzie jedziemy do WMS-a i w metrach da sie
# uczciwie wymusic kwadrat. Kolejnosc kolumn jest pozycyjna — trasa nie potrzebuje nazw.
ROOF_BBOX_SQL = """
SELECT ST_XMin(envelope), ST_YMin(envelope), ST_XMax(envelope), ST_YMax(envelope)
FROM (
    SELECT ST_Envelope(ST_Transform(geom, 3857)) AS envelope
    FROM osm_buildings
    WHERE id = %(id)s
) AS building
"""

Bbox = tuple[float, float, float, float]


class ImageryUnavailable(Exception):
    """Zewnetrzne zrodlo nie dalo obrazu. Trasa zamienia to na 503, nigdy na 500."""


def tile_bbox(zoom: int, x: int, y: int) -> Bbox:
    """Zakres kafla XYZ w EPSG:3857 — dokladnie ta sama siatka, ktorej uzywa MapLibre."""
    span = 2 * ORIGIN_SHIFT_M / (1 << zoom)
    min_x = -ORIGIN_SHIFT_M + x * span
    max_y = ORIGIN_SHIFT_M - y * span
    return (min_x, max_y - span, min_x + span, max_y)


def square_bbox(bbox: Bbox, margin: float = ROOF_MARGIN, min_span_m: float = ROOF_MIN_SPAN_M) -> Bbox:
    """Kwadrat wokol bboksu budynku z marginesem.

    Kwadrat jest wymogiem, nie ozdoba: WMS wpisuje dowolny bbox w podane WIDTH/HEIGHT, wiec
    prostokatny bbox przy kwadratowym obrazie rozciaga dach. Margines liczymy od dluzszego boku,
    zeby dach nie dotykal krawedzi kadru.
    """
    min_x, min_y, max_x, max_y = bbox
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    span = max(max(max_x - min_x, max_y - min_y) * (1 + margin), min_span_m)
    half = span / 2
    return (center_x - half, center_y - half, center_x + half, center_y + half)


def getmap_params(bbox: Bbox, width: int, height: int, layer: str) -> dict[str, str]:
    """Parametry GetMap. STYLES musi byc obecne i puste — brak tego parametru to blad w 1.3.0."""
    return {
        "SERVICE": "WMS",
        "VERSION": WMS_VERSION,
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": WMS_CRS,
        "BBOX": ",".join(f"{value:.3f}" for value in bbox),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": IMAGE_MEDIA_TYPE,
        "TRANSPARENT": "FALSE",
    }


def looks_like_png(content_type: str | None, payload: bytes) -> bool:
    """Naglowek bywa klamliwy, a XML z bledem przychodzi z kodem 200 — sprawdzamy oba tropy."""
    declared = (content_type or "").split(";")[0].strip().lower()
    return declared.startswith("image/") and payload.startswith(PNG_MAGIC)


class TileCache:
    """LRU na kafle: twardy limit liczby wpisow i sumy bajtow, bez zewnetrznej biblioteki.

    Kafle ortofoto sa niezmienne, wiec najtanszy cache oplaca sie od razu: przy przewijaniu mapy
    tam i z powrotem przegladarka i tak pyta o te same kafle, a my nie mielimy cudzej uslugi.
    """

    def __init__(self, max_entries: int = 256, max_bytes: int = 64 * 1024 * 1024) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.total_bytes = 0
        self._items: OrderedDict[tuple[Any, ...], bytes] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: tuple[Any, ...]) -> bytes | None:
        payload = self._items.get(key)
        if payload is None:
            return None
        self._items.move_to_end(key)
        return payload

    def put(self, key: tuple[Any, ...], payload: bytes) -> None:
        if len(payload) > self.max_bytes:  # jeden przerosniety wpis nie moze wyczyscic calego cache
            return
        existing = self._items.pop(key, None)
        if existing is not None:
            self.total_bytes -= len(existing)
        self._items[key] = payload
        self.total_bytes += len(payload)
        while self._items and (len(self._items) > self.max_entries or self.total_bytes > self.max_bytes):
            _, dropped = self._items.popitem(last=False)
            self.total_bytes -= len(dropped)


class ImageryClient:
    """Jeden klient HTTP na aplikacje: pooling, limit rownoleglosci i cache kafli.

    Klient tworzymy leniwie i pod `asyncio.Lock`, bo `httpx.AsyncClient` musi powstac w tej petli,
    ktora go uzywa; tworzenie go na kazde zadanie zabiloby pooling polaczen i handshake TLS.
    """

    def __init__(
        self,
        base_url: str,
        layer: str,
        timeout_s: float = 10.0,
        max_parallel: int = 4,
        cache: TileCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.layer = layer
        self.timeout_s = timeout_s
        self.max_parallel = max_parallel
        self.cache = cache if cache is not None else TileCache()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(max_parallel)

    @classmethod
    def from_settings(cls, settings: Any) -> "ImageryClient":
        return cls(
            base_url=settings.imagery_wms_url,
            layer=settings.imagery_wms_layer,
            timeout_s=settings.imagery_timeout_s,
            max_parallel=settings.imagery_max_parallel,
            cache=TileCache(settings.imagery_cache_tiles, settings.imagery_cache_mb * 1024 * 1024),
        )

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._lock:
                if self._client is None:  # druga proba pod blokada: rownolegle zadania startuja razem
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self.timeout_s),
                        transport=self._transport,
                        limits=httpx.Limits(max_connections=self.max_parallel, keepalive_expiry=30.0),
                        headers={"User-Agent": "Roofer/0.1 (+ortofoto proxy)"},
                    )
        return self._client

    async def fetch(self, bbox: Bbox, width: int, height: int) -> bytes:
        """GetMap albo ImageryUnavailable. Semafor pilnuje, ile zapytan leci do GUGiK naraz."""
        client = await self._http()
        try:
            async with self._slots:
                response = await client.get(self.base_url, params=getmap_params(bbox, width, height, self.layer))
        except httpx.HTTPError as error:  # timeout, DNS, zerwane TLS — wszystko konczy sie 503
            raise ImageryUnavailable(f"GUGiK nie odpowiedzial: {error!r}") from error
        if response.status_code != httpx.codes.OK:
            raise ImageryUnavailable(f"GUGiK odpowiedzial {response.status_code}.")
        payload = response.content
        if not looks_like_png(response.headers.get("content-type"), payload):
            raise ImageryUnavailable("Odpowiedz GUGiK nie jest PNG-iem (prawdopodobnie ServiceException).")
        return payload

    async def tile(self, zoom: int, x: int, y: int) -> bytes:
        key = (self.layer, zoom, x, y)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        payload = await self.fetch(tile_bbox(zoom, x, y), TILE_PIXELS, TILE_PIXELS)
        self.cache.put(key, payload)
        return payload

    async def roof(self, bbox: Bbox, size: int) -> bytes:
        """Wycinek dachu nie idzie do cache: kadr jest jednorazowy, a obrazy sa duze."""
        return await self.fetch(square_bbox(bbox), size, size)

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()


def client_for(app: Any) -> ImageryClient:
    """Instancja trzymana na `app.state`, tworzona przy pierwszym zadaniu.

    Bez awaitu miedzy sprawdzeniem i zapisem, wiec w jednowatkowej petli nie ma tu wyscigu;
    testy moga podstawic wlasnego klienta, ustawiajac `app.state.imagery` przed zapytaniem.
    """
    existing = getattr(app.state, "imagery", None)
    if existing is None:
        existing = ImageryClient.from_settings(app.state.settings)
        app.state.imagery = existing
    return existing


async def read_roof_bbox(pool: Any, building_id: int, timeout: float) -> Bbox | None:
    async with pool.connection(timeout=timeout) as connection:
        cursor = await connection.execute(ROOF_BBOX_SQL, {"id": building_id})
        row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
