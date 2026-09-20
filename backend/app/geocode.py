"""Wyszukiwanie miejscowosci i adresow przez Nominatim (OpenStreetMap).

Nominatim jest darmowy, ale jego regulamin
(https://operations.osmfoundation.org/policies/nominatim/) stawia warunki i zlamanie ich konczy
sie blokada adresu IP. Dlatego w tym pliku sa:

* User-Agent identyfikujacy aplikacje (`settings.nominatim_user_agent`) — anonimowe zapytania
  Nominatim odrzuca,
* ogranicznik najwyzej jednego zapytania na sekunde (RateLimiter); jesli kolejka wyszlaby dluzsza
  niz MAX_WAIT_S, lepiej powiedziec uzytkownikowi „sprobuj za chwile" niz trzymac zadanie,
* cache w pamieci na znormalizowana fraze, bo powtarzanie tego samego zapytania jest wprost
  zabronione,
* jeden wspolny httpx.AsyncClient, tworzony leniwie — nowy klient na kazde zadanie to nowe
  polaczenie TLS do Nominatima przy kazdym nacisnieciu klawisza.

Padniety Nominatim nie moze wywalic naszego API: kazdy blad sieci konczy sie 503
z komunikatem dla uzytkownika (po angielsku, bo taki jest interfejs), nigdy 500 z tracebackiem.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT_S = 5.0
MIN_INTERVAL_S = 1.0  # regulamin: maks. 1 zapytanie na sekunde na caly serwis
MAX_WAIT_S = 2.0  # dluzej nie kolejkujemy — zamiast wisiec, oddajemy 429
CACHE_LIMIT = 256
DEFAULT_LIMIT = 5
MAX_LIMIT = 10


class GeocodeError(Exception):
    """Blad wyszukiwania z gotowym kodem HTTP i komunikatem widocznym w interfejsie."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class EmptyQueryError(GeocodeError):
    def __init__(self) -> None:
        super().__init__(400, "Enter a place name or an address to search for.")


class RateLimitedError(GeocodeError):
    def __init__(self) -> None:
        super().__init__(429, "Too many requests to the place search. Try again in a moment.")


class UpstreamError(GeocodeError):
    def __init__(self) -> None:
        super().__init__(503, "The place search (Nominatim) is not responding. Try again in a moment.")


def normalize_query(raw: str) -> str:
    """Klucz cache'a: bez wielkosci liter i bez nadmiarowych spacji, wiec „ Zwolen " == „zwolen"."""
    return " ".join(raw.split()).lower()


def clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def search_params(query: str, limit: int) -> dict[str, str]:
    """`jsonv2` daje `addresstype` i `boundingbox`, `countrycodes=pl` obcina wyniki spoza Polski.

    `accept-language=en` dotyczy tego, co uzytkownik czyta w podpowiedziach: interfejs jest po
    angielsku, wiec podzialy administracyjne maja brzmiec „Masovian Voivodeship, Poland", a nie
    „wojewodztwo mazowieckie". Nazwy wlasne miejscowosci Nominatim i tak oddaje po polsku
    („Zwolen", „Warszawa") — i tak ma byc, bo to sa ich nazwy.
    """
    return {
        "format": "jsonv2",
        "countrycodes": "pl",
        "accept-language": "en",
        "limit": str(clamp_limit(limit)),
        "q": query,
    }


def to_bbox(raw: Any) -> list[float] | None:
    """Konwersja `boundingbox` Nominatima na nasza kolejnosc.

    Nominatim oddaje cztery STRINGI w kolejnosci [south, north, west, east] (najpierw obie
    szerokosci, potem obie dlugosci). My zwracamy [south, west, north, east], czyli naroznik
    poludniowo-zachodni i pozniej polnocno-wschodni. Obie kolejnosci zaczynaja sie od poludnia,
    wiec pomylka nie rzuca bledem — tylko przesuwa mape w morze. Stad ta funkcja i jej test.
    """
    if not isinstance(raw, list | tuple) or len(raw) != 4:
        return None
    try:
        south, north, west, east = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    return [south, west, north, east]


def to_place(item: Any) -> dict[str, Any] | None:
    """Jeden wynik Nominatima na nasz model; niekompletny wpis pomijamy, a nie psujemy nim listy."""
    if not isinstance(item, dict):
        return None
    label = item.get("display_name")
    if not isinstance(label, str) or not label.strip():
        return None
    try:
        lat = float(item["lat"])
        lng = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    # `addresstype` mowi najkonkretniej, co to jest (village, town, road); `type` i `category`
    # to zapas dla starszych odpowiedzi.
    kind = item.get("addresstype") or item.get("type") or item.get("category")
    return {
        "label": label,
        "lat": lat,
        "lng": lng,
        "bbox": to_bbox(item.get("boundingbox")),
        "kind": kind if isinstance(kind, str) and kind else None,
    }


def to_places(payload: Any) -> list[dict[str, Any]]:
    """Nominatim ma oddac liste. Cokolwiek innego traktujemy jak awarie zrodla, nie jak brak wynikow."""
    if not isinstance(payload, list):
        raise UpstreamError
    return [place for place in (to_place(item) for item in payload) if place is not None]


def slot_delay(next_allowed_s: float | None, now_s: float) -> float:
    """Ile sekund trzeba odczekac przed nastepnym zapytaniem — czysta funkcja, stan w argumencie."""
    if next_allowed_s is None:
        return 0.0
    return max(0.0, next_allowed_s - now_s)


class RateLimiter:
    """Najwyzej jedno zapytanie na `min_interval_s`.

    Kazde zadanie rezerwuje swoje okno pod blokada i spi POZA nia, wiec dwa rownolegle zapytania
    nie budza sie w tej samej chwili. Gdy rezerwacja wypadalaby dalej niz `max_wait_s`, rzucamy
    RateLimitedError — kolejka bez granicy tylko przeklada timeout na przegladarke.
    """

    def __init__(
        self,
        min_interval_s: float = MIN_INTERVAL_S,
        max_wait_s: float = MAX_WAIT_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.max_wait_s = max_wait_s
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_allowed_s: float | None = None

    async def acquire(self) -> float:
        """Zwraca, ile sekund przeczekala — przydatne w logach i testach."""
        async with self._lock:
            now = self._clock()
            delay = slot_delay(self._next_allowed_s, now)
            if delay > self.max_wait_s:
                raise RateLimitedError
            self._next_allowed_s = now + delay + self.min_interval_s
        if delay > 0.0:
            await self._sleep(delay)
        return delay


class LruCache:
    """Maly cache LRU na wyniki wyszukiwania; powtorzone zapytanie nie idzie do Nominatima."""

    def __init__(self, limit: int = CACHE_LIMIT) -> None:
        self.limit = max(1, limit)
        self._entries: OrderedDict[Any, Any] = OrderedDict()

    def get(self, key: Any) -> Any | None:
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: Any, value: Any) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self.limit:
            self._entries.popitem(last=False)  # wypada najdawniej uzywany wpis

    def __len__(self) -> int:
        return len(self._entries)


class Geocoder:
    """Wspoldzielony dostep do Nominatima: jeden klient HTTP, jeden ogranicznik, jeden cache."""

    def __init__(
        self,
        user_agent: str,
        url: str = NOMINATIM_URL,
        timeout_s: float = TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_limit: int = CACHE_LIMIT,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.url = url
        self.timeout_s = timeout_s
        self.cache = LruCache(cache_limit)
        self.limiter = limiter or RateLimiter()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def client(self) -> httpx.AsyncClient:
        """Klient powstaje przy pierwszym zapytaniu i zyje do konca procesu."""
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=self.timeout_s,
                    headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                    transport=self._transport,
                )
        return self._client

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def search(self, raw_query: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
        query = normalize_query(raw_query)
        if not query:
            raise EmptyQueryError
        limit = clamp_limit(limit)
        key = (query, limit)  # limit jest czescia klucza, bo wynik dla 5 nie zastapi wyniku dla 10
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        await self.limiter.acquire()
        places = to_places(await self._fetch(query, limit))
        self.cache.put(key, places)
        return places

    async def _fetch(self, query: str, limit: int) -> Any:
        client = await self.client()
        try:
            response = await client.get(self.url, params=search_params(query, limit))
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            # timeout, zerwane polaczenie, 5xx albo strona HTML zamiast JSON-a — wszystko to 503
            raise UpstreamError from error


def get_geocoder(app: Any) -> Geocoder:
    """Jeden Geocoder na aplikacje, tworzony przy pierwszym zapytaniu.

    Miedzy sprawdzeniem i zapisem nie ma `await`, wiec petla zdarzen nie wejdzie tu po raz drugi
    i nie powstana dwa ograniczniki (czyli 2 zapytania na sekunde do Nominatima). Stan trzymamy
    w `app.state`, zeby testy dostawaly czysty cache razem z nowa aplikacja.
    """
    geocoder: Geocoder | None = getattr(app.state, "geocoder", None)
    if geocoder is None:
        settings = app.state.settings
        geocoder = Geocoder(
            user_agent=settings.nominatim_user_agent,
            url=settings.nominatim_url,
            timeout_s=settings.nominatim_timeout_s,
        )
        app.state.geocoder = geocoder
    return geocoder
