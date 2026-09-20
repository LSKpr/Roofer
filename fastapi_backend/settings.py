from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_path: Path = ROOT / "fastapi_backend/data/buildings.sqlite"
    model_path: Path = ROOT / "artifacts/roof_classifier_quality_v2_server/model.onnx"
    token_file: Path = ROOT / "fastapi_backend/runtime/api-token"
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:5173")
    max_buildings: int = 100
    max_area_km2: float = 4.0
    request_timeout: float = 180.0
    tile_timeout: float = 15.0
    tile_concurrency: int = 8
    tile_cache_bytes: int = 32 * 1024 * 1024
    tile_cache_ttl: float = 3600.0
    batch_size: int = 8
    model_threads: int = 4
    requests_per_minute: int = 10

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        values = {}
        for field in fields(cls):
            raw = os.environ.get(f"ROOFER_{field.name.upper()}")
            if raw is None:
                continue
            default = getattr(defaults, field.name)
            if isinstance(default, Path):
                values[field.name] = Path(raw).expanduser().resolve()
            elif isinstance(default, tuple):
                values[field.name] = tuple(item.strip() for item in raw.split(",") if item.strip())
            else:
                values[field.name] = type(default)(raw)
        result = cls(**values)
        for field in fields(cls):
            value = getattr(result, field.name)
            if isinstance(value, (int, float)) and (not 0 < value < float("inf")):
                raise ValueError(f"ROOFER_{field.name.upper()} must be finite and positive")
        return result
