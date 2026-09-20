import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

INDEX_URL = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/SkorowidzeWgRozdzielczosci"
INDEX_LAYERS = "SkorowidzeOrtofotomapyDo5cm,SkorowidzeOrtofotomapyPowyzej5Do10cm,SkorowidzeOrtofotomapyPowyzej10cm"
SOURCE_URL_PATTERN = re.compile(r"https://opendata\.geoportal\.gov\.pl/ortofotomapa/\d+/[A-Za-z0-9_.-]+\.(?:tif|TIF)")
INDEX_ARRAYS = ("skorDo5cm", "skor510cm", "skorOd10cm")
ROW_PATTERN = re.compile(r"\b(skorDo5cm|skor510cm|skorOd10cm)\.push\(\{(.*?)\}\);", re.DOTALL)


class CropError(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status = status


@dataclass(frozen=True)
class OrthoSource:
    url: str
    sheet: str
    acquisition_date: date
    resolution_m: float


@dataclass(frozen=True)
class CachedRaster:
    path: Path
    sha256: str
    size_bytes: int


def parse_record(body: str) -> dict[str, str]:
    decoder = json.JSONDecoder()
    values = {}
    position = 0
    while position < len(body):
        key = re.compile(r"\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*").match(body, position)
        if key is None:
            raise ValueError("Invalid metadata field")
        value, position = decoder.raw_decode(body, key.end())
        if not isinstance(value, str) or key[1] in values:
            raise ValueError("Expected unique string metadata fields")
        values[key[1]] = value
        separator = re.compile(r"\s*(,|$)\s*").match(body, position)
        if separator is None:
            raise ValueError("Invalid metadata separator")
        position = separator.end()
    return values


def parse_sources(document: str, year: int | None = None) -> list[OrthoSource]:
    if "ServiceException" in document or "ExceptionReport" in document:
        raise CropError("source_unavailable", "GUGiK returned an OGC exception instead of the imagery index.")
    present_groups = {name for name in INDEX_ARRAYS if re.search(rf"\bvar\s+{name}\s*=\s*\[\s*\]", document)}
    if not present_groups:
        raise CropError("invalid_metadata", "Unrecognized GUGiK index format; refusing to guess image metadata.")
    rows = ROW_PATTERN.findall(document)
    if any(name not in present_groups for name, _ in rows) or len(rows) != len(re.findall(r"\b(?:skorDo5cm|skor510cm|skorOd10cm)\.push\(", document)) or len(rows) >= 100:
        raise CropError("invalid_metadata", "Malformed or potentially truncated GUGiK index response.")
    sources = {}
    try:
        for _, body in rows:
            record = parse_record(body)
            if record["kolor"] != "RGB":
                continue
            url = record["url"]
            resolution = float(record["wielkoscPiksela"])
            acquired = date.fromisoformat(record["aktualnosc"])
            if SOURCE_URL_PATTERN.fullmatch(url) is None or not math.isfinite(resolution) or resolution <= 0 or not record["godlo"]:
                raise ValueError("Invalid source metadata")
            if year is None or acquired.year == year:
                source = OrthoSource(url, record["godlo"], acquired, resolution)
                if url in sources and sources[url] != source:
                    raise ValueError("Conflicting source metadata")
                sources[url] = source
    except (KeyError, ValueError) as error:
        raise CropError("invalid_metadata", "GUGiK RGB records contain invalid dates, resolution, or download URLs.") from error
    if not sources:
        raise CropError("no_coverage", "No RGB imagery found for this location and requested year.")
    usable = [source for source in sources.values() if source.resolution_m <= 0.25]
    if not usable:
        raise CropError("insufficient_resolution", "Available RGB imagery is coarser than 0.25 m/pixel.")
    return sorted(usable, key=lambda source: (source.resolution_m, -source.acquisition_date.toordinal(), source.url))


def discover_sources(client: httpx.Client, longitude: float, latitude: float, year: int | None = None) -> list[OrthoSource]:
    delta = 0.000001
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
        "LAYERS": INDEX_LAYERS, "QUERY_LAYERS": INDEX_LAYERS, "CRS": "EPSG:4326",
        "BBOX": f"{latitude - delta},{longitude - delta},{latitude + delta},{longitude + delta}",
        "WIDTH": "101", "HEIGHT": "101", "I": "50", "J": "50",
        "INFO_FORMAT": "text/html", "FEATURE_COUNT": "100",
    }
    try:
        with client.stream("GET", INDEX_URL, params=params) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes(65536):
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024:
                    raise CropError("invalid_metadata", "GUGiK index response exceeds the size limit.")
    except httpx.HTTPError as error:
        raise CropError("source_unavailable", "Could not retrieve the GUGiK imagery index.") from error
    try:
        document = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CropError("invalid_metadata", "GUGiK index is not valid UTF-8.") from error
    return parse_sources(document, year)


def download_source(client: httpx.Client, source: OrthoSource, cache_dir: Path, max_download_bytes: int) -> CachedRaster:
    if SOURCE_URL_PATTERN.fullmatch(source.url) is None:
        raise CropError("invalid_metadata", "Only official GUGiK orthophoto download URLs are supported.")
    key = hashlib.sha256(source.url.encode()).hexdigest()
    path = cache_dir / f"{key}.tif"
    manifest_path = cache_dir / f"{key}.json"
    if path.exists() or manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            size = path.stat().st_size
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if manifest != {"url": source.url, "size_bytes": size, "sha256": digest}:
                raise ValueError("Cache checksum mismatch")
        except (OSError, ValueError) as error:
            raise CropError("invalid_cache", f"Invalid cached raster or manifest: {path}. Use another --cache-dir or inspect the cache.") from error
        return CachedRaster(path, digest, size)
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        with client.stream("GET", source.url, headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length is not None and not length.isdigit():
                raise CropError("source_unavailable", "Invalid download Content-Length.")
            if length is not None and int(length) > max_download_bytes:
                raise CropError("download_limit", f"Selected original needs {int(length) / 1024**2:.1f} MiB; raise --max-download-mb explicitly or choose another --year.")
            with TemporaryDirectory(prefix=".download-", dir=cache_dir) as temporary:
                partial = Path(temporary) / "source.tif"
                digest = hashlib.sha256()
                size = 0
                with partial.open("wb") as stream:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > max_download_bytes:
                            raise CropError("download_limit", "Original exceeds --max-download-mb; partial download discarded.")
                        stream.write(chunk)
                        digest.update(chunk)
                if not size or (length is not None and size != int(length)):
                    raise CropError("source_unavailable", "Incomplete original raster download.")
                with partial.open("rb") as stream:
                    if stream.read(4) not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
                        raise CropError("invalid_raster", "Download is not a TIFF raster.")
                checksum = digest.hexdigest()
                manifest = Path(temporary) / "source.json"
                manifest.write_text(json.dumps({"url": source.url, "size_bytes": size, "sha256": checksum}), encoding="utf-8")
                os.replace(partial, path)
                os.replace(manifest, manifest_path)
    except httpx.HTTPError as error:
        raise CropError("source_unavailable", "Original raster download failed; no incomplete file is reused.") from error
    return CachedRaster(path, checksum, size)
