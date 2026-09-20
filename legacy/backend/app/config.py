from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, enable_decoding=False)

    database_url: str = "postgresql+psycopg://roofer:roofer@localhost:5432/roofer"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    geoazbest_wfs_url: str = "https://esip.bazaazbestowa.gov.pl/geoserver/wfs/ows"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    building_provider: str = "overpass"
    demo_fallback_enabled: bool = True
    max_analysis_area_km2: float = 25.0
    external_timeout_seconds: float = 30.0
    wfs_page_size: int = 500
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | list[str]) -> list[str]:
        return value.split(",") if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
