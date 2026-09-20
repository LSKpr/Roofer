from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Jedno zrodlo prawdy dla limitow uslugi modelu; `app.prediction` nie importuje konfiguracji,
# wiec ten kierunek nie tworzy cyklu.
from app.prediction import MODEL_MAX_AREA_KM2, MODEL_MAX_BUILDINGS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://roofer:roofer@localhost:5433/roofer"
    database_timeout_s: float = 3.0
    cors_origins: str = "http://localhost:5173"
    api_port: int = 8001

    # Jak dlugo token wersji danych (ETag kafli) moze byc podawany z pamieci procesu. Jedno
    # przesuniecie mapy to kilkadziesiat kafli, wiec bez tego bufora kazdy kafel pytalby baze
    # o te sama wartosc. Tyle samo sekund wynosi maksymalne opoznienie uniewaznienia cache'a
    # po imporcie — import trwa minuty, wiec to nie ma znaczenia.
    data_version_ttl_s: float = 5.0

    # Ortofotomapa GUGiK (WMS 1.3.0, warstwa Raster). StandardResolution jest domyslne, bo
    # HighResolution ma pokrycie tylko nad miastami i poza nimi oddaje pusty kafel.
    imagery_wms_url: str = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution"
    imagery_wms_layer: str = "Raster"
    imagery_timeout_s: float = 10.0
    imagery_max_parallel: int = 4
    # Cache kafli i wycinkow dachow w pamieci procesu. Rozmiar wziety z pomiaru, nie z sufitu:
    # obszar demo (okolice Zwolenia, ~5 km²) to na zoomach 13-19 dokladnie 3 176 kafli po srednio
    # 113 KB, czyli ~349 MB. Przy slabej sieci na miejscu cache jest jedyna rzecza, ktora trzyma
    # ortofoto na ekranie, a rozgrzewa sie go OGLADAJAC obszar w przegladarce — nie skryptem,
    # bo skryptowe przemiatanie siatki to harvesting, ktory regulamin GUGiK wyklucza (patrz
    # naglowek app/imagery.py). Restart procesu czysci pamiec i trzeba rozgrzac ponownie.
    imagery_cache_tiles: int = 6000
    imagery_cache_mb: int = 768

    # Wyszukiwanie miejsc (Nominatim OSM). Regulamin wymaga User-Agenta, ktory identyfikuje
    # aplikacje i pozwala sie z nami skontaktowac; anonimowe zapytania sa blokowane.
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    nominatim_user_agent: str = "Roofer/0.1 (inwentaryzacja azbestu; https://github.com/LSKpr/Roofer)"
    nominatim_timeout_s: float = 5.0

    # Ocena pokrycia dachu (gniazdo na model ML). `mock` to jawnie oznaczona atrapa: odpowiedz ma
    # `source: "mock"`, `modelName: null` i note o wyniku demonstracyjnym. `none` wylacza ocene —
    # endpoint oddaje wtedy `source: "unavailable"` i `probability: null`, czyli „nie wiemy".
    # Dostawce prawdziwego modelu dopisuje sie w app/prediction.py (PROVIDERS), nie w trasie.
    prediction_provider: str = "mock"

    # Zewnetrzne API modelu (`model`). Bez adresu albo bez tokenu dostawca degraduje sie do „nie
    # wiemy" zamiast pytac i dostawac 401. TOKEN JEST SEKRETEM: trzymamy go w .env, ktory jest
    # w .gitignore, i nie wypisujemy go nigdzie — HttpModelProvider ma wlasny `__repr__`.
    prediction_api_url: str = ""
    # SecretStr, a nie str: pydantic wypisuje cale Settings w komunikacie bledu i w logu startu,
    # wiec zwykly napis wyciekl do pierwszego lepszego tracebacku. Zlapal to test, ktory sprawdzal
    # co innego — wartosc widac tylko przez `.get_secret_value()`.
    prediction_api_token: SecretStr = SecretStr("")
    prediction_timeout_s: float = 60.0
    # Ocena tego samego dachu z tego samego zdjecia sie nie zmienia, wiec cache nie falszuje
    # odpowiedzi, a chroni przed limitem 10 zapytan na minute po stronie tamtej instancji.
    prediction_cache_ttl_s: float = 3600.0
    prediction_min_interval_s: float = 6.0
    # Skan obszaru pyta o setki budynkow naraz, wiec ma wlasny, dluzszy limit czasu. Usluga modelu
    # i tak przerywa zadanie po 180 s — czekanie dluzej niczego by nie doczekalo.
    prediction_area_timeout_s: float = 180.0
    # Limity USLUGI modelu, ktore odwzorowuje nasza bramka (patrz MODEL_MAX_* w app/prediction.py).
    # Trzymamy je w konfiguracji, bo naleza do uruchomionej instancji: lokalna kopia przyjmuje
    # tyle, ile jej ustawimy przez ROOFER_MAX_BUILDINGS, a wspoldzielona instancja miala 100 i 4 km2.
    prediction_model_max_buildings: int = MODEL_MAX_BUILDINGS
    prediction_model_max_area_km2: float = MODEL_MAX_AREA_KM2

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
