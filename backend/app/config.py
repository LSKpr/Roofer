from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    imagery_cache_tiles: int = 256
    imagery_cache_mb: int = 64

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

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
