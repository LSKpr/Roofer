"""Wersja danych i ETag kafla, czyli cache walidowany zamiast cache'a na czas.

Kafel wektorowy niesie identyfikatory budynkow z bazy, a ponowny import je zmienia (TRUNCATE nie
zeruje sekwencji — pulapka 21 w AGENTS.md). Przy `Cache-Control: public, max-age=3600` przegladarka
przez godzine rysowala kafle ze starymi identyfikatorami: klik w budynek wysylal numer, ktorego
w bazie juz nie ma, i backend oddawal 404. Krotsze max-age tego nie naprawia — kazda wartosc jest
albo za dluga (mapa klamie po imporcie), albo za krotka (kafle leca do bazy bez potrzeby).

Naprawa: kafel jest `no-cache` z ETagiem. Przegladarka moze go trzymac dowolnie dlugo, ale przed
uzyciem musi dopytac, a serwer porownuje jej ETag z tokenem z tabeli `data_version` (migracja 005).
Import podbija token w tej samej transakcji co dane, wiec nie ma stanu „nowe dane, stary token".

Token pilnuje jednak tylko DANYCH. Kafel zmienia sie takze wtedy, gdy zmieni sie kod: przejscie
z identyfikatorow z sekwencji na `osm_id` daje przy tych samych danych inna tresc kafla, a token
zostaje ten sam. Dlatego w ETagu jest drugi skladnik, TILE_SCHEMA_VERSION — bez niego przegladarka
dostalaby 304 na kafel ze starymi identyfikatorami i odtworzylaby ten sam blad 404.

Odczyt tokenu jest buforowany w pamieci procesu na kilka sekund, bo jedno przesuniecie mapy to
kilkadziesiat kafli i tyle samo pytan o te sama wartosc.
"""

import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

READ_TOKEN_SQL = "SELECT token FROM data_version WHERE only_row"

# INSERT ... ON CONFLICT, a nie UPDATE, bo wiersz ma istniec takze wtedy, gdy ktos go skasowal
# recznie — import bez tokenu wersji zostawilby mape z cache'em, ktorego nikt nie uniewazni.
BUMP_TOKEN_SQL = """
INSERT INTO data_version (only_row, token, updated_at) VALUES (true, %(token)s, now())
ON CONFLICT (only_row) DO UPDATE SET token = excluded.token, updated_at = excluded.updated_at
"""

# Ile sekund token moze byc podawany z pamieci procesu. To zarazem maksymalne opoznienie
# uniewaznienia cache'a po imporcie: import trwa minuty, wiec kilka sekund nic nie psuje.
CACHE_TTL_S = 5.0

# Wersja SCHEMATU kafla, czyli jego tresci i znaczenia. KAZDA zmiana tego, co kafel niesie, wymaga
# podbicia tej liczby: inne znaczenie identyfikatora obiektu, inny atrybut, inny prog zoomu, inny
# extent. Token wersji danych tego nie zalatwia, bo on zmienia sie przy imporcie, a to jest zmiana
# KODU przy niezmienionych danych — bez tego skladnika przegladarka potwierdzilaby swiezosc kafla,
# ktory lezy u niej w cache, i dalej rysowalaby stara tresc.
#
# 1 — identyfikator obiektu to klucz `id` z sekwencji bazy (stan do 2026-09-21),
# 2 — identyfikator obiektu to `osm_id`, bo klucz z sekwencji nie przezywa ponownego importu
#     (pulapka 21 w AGENTS.md) i klik w budynek z kafla w cache konczyl sie 404,
# 3 — zoomy 8-13 nie niosa juz centroidow zgloszonych budynkow (warstwa `listed`), tylko siatke
#     gestosci: warstwa `listed_density`, jeden punkt na komorke z atrybutem `count` i bez
#     identyfikatora obiektu. Dane sie nie zmienily, wiec bez tego skladnika przegladarka
#     dostalaby 304 na kafel ze stara warstwa i heatmapa nie pojawilaby sie az do wygasniecia
#     jej cache'a.
TILE_SCHEMA_VERSION = 3


def new_token() -> str:
    """Nowy token wersji danych.

    Losowy, a nie skrot z danych: po pierwsze skrot 2,58 mln poligonow trzeba by policzyc, po
    drugie „dane sa takie same" nie znaczy tutaj „kafle sa takie same" — ponowny import tego samego
    pliku nadaje budynkom inne identyfikatory. Tokenu, ktory zmienia sie zawsze, nie da sie przeoczyc.
    """
    return uuid4().hex


def bump_version(connection: Any, token: str | None = None) -> str:
    """Podbija token wersji danych i zwraca nowa wartosc.

    Swiadomie bez commita: wywolujacy trzyma te sama transakcje co wstawiane dane. Osobny commit
    tokenu otwieralby okno, w ktorym w bazie sa nowe identyfikatory, a serwer nadal potwierdza
    swiezosc starych kafli — czyli dokladnie ten blad, ktory ten modul ma zlikwidowac.
    """
    token = token or new_token()
    with connection.cursor() as cursor:
        cursor.execute(BUMP_TOKEN_SQL, {"token": token})
    return token


def tile_etag(token: str | None, z: int, x: int, y: int) -> str | None:
    """ETag kafla: wersja schematu, token wersji danych i wspolrzedne.

    Token odpowiada za to, ze po imporcie zaden stary kafel nie zostanie uznany za swiezy,
    TILE_SCHEMA_VERSION za to samo po zmianie tresci albo znaczenia kafla w kodzie (dane moga byc
    wtedy identyczne, wiec token sie nie ruszy), a wspolrzedne za to, ze kafle nie potwierdzaja
    swiezosci jeden drugiemu. Bez tokenu ETagu nie ma: walidator, ktorego nie umiemy powiazac
    z wersja danych, jest gorszy niz jego brak.

    Walidator jest SLABY (`W/`), i to nie jest ostroznosc na zapas: ten sam kafel z tymi samymi
    danymi oddal raz 45 034, a raz 44 979 bajtow. ST_AsMVT nie ma ORDER BY, wiec kolejnosc obiektow
    zalezy od planu (rownolegly seq scan albo indeks) i bajty nie sa powtarzalne. Slaby ETag mowi
    „ta sama tresc", a nie „te same bajty" — i tylko to umiemy obiecac.
    """
    if not token:
        return None
    return f'W/"v{TILE_SCHEMA_VERSION}-{token}-{z}-{x}-{y}"'


def etag_matches(if_none_match: str | None, etag: str | None) -> bool:
    """Czy klient ma juz dokladnie te wersje kafla (naglowek If-None-Match, RFC 9110).

    Naglowek moze nosic liste ETagow rozdzielona przecinkami i prefiks `W/` — porownujemy slabo,
    czyli ten prefiks pomijamy. `*` nie jest tu dopasowaniem: znaczy „jesli kafel istnieje", a tego
    bez zapytania do PostGIS-a nie wiemy, wiec odpowiadamy normalnym kaflem.
    """
    if not if_none_match or not etag:
        return False
    return any(_without_weak_prefix(value) == _without_weak_prefix(etag) for value in if_none_match.split(","))


def _without_weak_prefix(value: str) -> str:
    return value.strip().removeprefix("W/")


async def read_token(pool: Any, timeout: float) -> str | None:
    """Token z bazy albo None, gdy wiersza nie ma lub baza nie odpowiada.

    Blad jest polykany swiadomie. Brak tokenu ma dac kafel bez ETagu i bez cache'a (patrz trasa
    kafli), a nie 500 na calej mapie: kafel bez walidatora jest tylko drozszy, nigdy nieprawdziwy.
    """
    try:
        async with pool.connection(timeout=timeout) as connection:
            cursor = await connection.execute(READ_TOKEN_SQL)
            row = await cursor.fetchone()
    except Exception:  # padnieta baza, brak tabeli, timeout — dla kafla to ta sama sytuacja
        return None
    if not row or not row[0]:
        return None
    return str(row[0])


class DataVersion:
    """Token wersji danych z krotkim cache'em w pamieci procesu.

    Zegar jest wstrzykiwany, wiec wygasniecie wpisu da sie sprawdzic w tescie bez `sleep`.
    Nieudany odczyt tez jest zapamietywany: przy padnietej bazie nie ma sensu pytac o token
    przy kazdym z kilkudziesieciu kafli.

    Blokady nie ma celowo — gdy cache jest zimny, kilka rownoleglych zadan moze wykonac to samo
    jednowierszowe SELECT. To tanszy wariant niz kolejkowanie zadan na blokadzie, a wynik jest
    identyczny, bo odczyt nic nie zmienia.
    """

    def __init__(self, ttl_s: float = CACHE_TTL_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = max(0.0, ttl_s)
        self._clock = clock
        self._token: str | None = None
        self._read_at_s: float | None = None

    def fresh(self) -> bool:
        """Czy wpis w pamieci jeszcze obowiazuje — czysta funkcja czasu, bez zapytania do bazy."""
        if self._read_at_s is None:
            return False
        return self._clock() - self._read_at_s <= self.ttl_s

    async def token(self, pool: Any, timeout: float) -> str | None:
        if self.fresh():
            return self._token
        self._token = await read_token(pool, timeout)
        self._read_at_s = self._clock()
        return self._token


def version_for(app: Any) -> DataVersion:
    """Jeden licznik wersji na aplikacje, tworzony leniwie.

    Stan siedzi w `app.state`, wiec nowa aplikacja w tescie dostaje czysty cache, a atrape podaje
    sie przez `app.state.data_version` bez zmian w main.py. Miedzy sprawdzeniem i zapisem nie ma
    `await`, wiec petla zdarzen nie wstawi tu drugiej instancji.
    """
    version: DataVersion | None = getattr(app.state, "data_version", None)
    if version is None:
        version = DataVersion(ttl_s=app.state.settings.data_version_ttl_s)
        app.state.data_version = version
    return version
