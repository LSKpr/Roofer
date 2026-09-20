import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import RegistryFeature, RegistrySyncCheckpoint

WFS_LAYERS = {
    "wfs:budynki_z_azbestem",
    "wfs:budynki_oczyszczone",
    "wfs:budynki",
    "wfs:wyroby_dzialki",
    "wfs:wyroby_rury",
}


class GeoAzbestUnavailable(RuntimeError):
    pass


class GeoAzbestWfsClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.url = settings.geoazbest_wfs_url
        self.page_size = settings.wfs_page_size
        self.timeout = settings.external_timeout_seconds
        self.transport = transport

    async def discover_schema(self, layer: str) -> str:
        self._validate_layer(layer)
        return await self._request_text({"service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType", "typeNames": layer})

    async def get_capabilities(self) -> str:
        return await self._request_text({"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"})

    async def iter_features(self, layer: str, bbox: list[float] | None = None, teryt: str | None = None, start_index: int = 0) -> AsyncIterator[tuple[dict[str, Any], int | None, int]]:
        self._validate_layer(layer)
        if teryt and (not teryt.isdigit() or len(teryt) > 20):
            raise ValueError("TERYT must contain only digits")
        index = start_index
        while True:
            params: dict[str, Any] = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": layer,
                "outputFormat": "json",
                "srsName": "EPSG:4326",
                "startIndex": index,
                "count": self.page_size,
            }
            if bbox:
                params["bbox"] = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:4326"
            if teryt:
                params["CQL_FILTER"] = f"teryt = '{teryt}'"
            payload = await self._request_json(params)
            features = payload.get("features", [])
            total = payload.get("numberMatched")
            total_expected = int(total) if str(total).isdigit() else None
            yield payload, total_expected, index
            returned = int(payload.get("numberReturned", len(features)) or 0)
            if returned == 0 or len(features) == 0 or (total_expected is not None and index + returned >= total_expected):
                break
            index += returned

    async def _request_json(self, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": "Roofer/0.1; public-service-respecting-client"}, transport=self.transport) as client:
                    response = await client.get(self.url, params=params)
                    response.raise_for_status()
                    return response.json()
            except (httpx.HTTPError, ValueError) as error:
                if attempt == 3:
                    raise GeoAzbestUnavailable(str(error)) from error
                await asyncio.sleep(2**attempt)
        raise GeoAzbestUnavailable("WFS request failed")

    async def _request_text(self, params: dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get(self.url, params=params)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as error:
            raise GeoAzbestUnavailable(str(error)) from error

    @staticmethod
    def _validate_layer(layer: str) -> None:
        if layer not in WFS_LAYERS:
            raise ValueError("Unsupported GeoAzbest layer")


def scope_key(layer: str, bbox: list[float] | None, teryt: str | None, full_country: bool) -> str:
    scope = {"layer": layer, "bbox": bbox, "teryt": teryt, "full_country": full_country}
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def status_for_feature(layer: str, properties: dict[str, Any]) -> str:
    if layer == "wfs:budynki_z_azbestem":
        return "listed"
    if layer == "wfs:budynki_oczyszczone":
        return "cleaned"
    if layer == "wfs:wyroby_dzialki":
        inventory = number(properties.get("ilosc_wyrobu"))
        disposed = number(properties.get("ilosc_przekazana_do_unieszkodliwienia"))
        if properties.get("rok_unieszkodliwienia_wyrobu") and inventory is not None and disposed is not None and disposed >= inventory:
            return "cleaned"
        return "listed"
    return "unknown"


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    number_value = number(value)
    return int(number_value) if number_value is not None else None


def feature_values(layer: str, feature: dict[str, Any]) -> dict[str, Any] | None:
    geometry_json = feature.get("geometry")
    if not geometry_json:
        return None
    geometry = shape(geometry_json)
    if geometry.is_empty or not geometry.is_valid:
        return None
    props = feature.get("properties") or {}
    source_id = str(feature.get("id") or props.get("id") or props.get("objectid") or hashlib.sha256(json.dumps(feature, sort_keys=True).encode()).hexdigest())
    return {
        "geoazbest_layer": layer,
        "source_feature_id": source_id,
        "location_id": str(props.get("id_lokalizacji") or props.get("id_lok") or "") or None,
        "parcel_number": str(props.get("nr_dzialki") or "") or None,
        "teryt": str(props.get("teryt") or "") or None,
        "geometry": from_shape(geometry, srid=4326),
        "registry_status": status_for_feature(layer, props),
        "urgency": str(props.get("stopien_pilnosci_opis") or props.get("stopien_pilnosci") or "") or None,
        "planned_removal_year": integer(props.get("planowany_rok_unieszkodliwienia_wyrobu")),
        "actual_removal_year": integer(props.get("rok_unieszkodliwienia_wyrobu")),
        "inventory_amount": number(props.get("ilosc_wyrobu")),
        "disposed_amount": number(props.get("ilosc_przekazana_do_unieszkodliwienia")),
        "raw_properties": props,
        "synchronized_at": datetime.now(timezone.utc),
    }


def upsert_feature(session: Session, values: dict[str, Any]) -> RegistryFeature:
    existing = session.scalar(select(RegistryFeature).where(RegistryFeature.geoazbest_layer == values["geoazbest_layer"], RegistryFeature.source_feature_id == values["source_feature_id"]))
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        return existing
    feature = RegistryFeature(**values)
    session.add(feature)
    return feature


async def synchronize_layer(session: Session, client: GeoAzbestWfsClient, layer: str, bbox: list[float] | None = None, teryt: str | None = None, full_country: bool = False) -> RegistrySyncCheckpoint:
    key = scope_key(layer, bbox, teryt, full_country)
    checkpoint = session.scalar(select(RegistrySyncCheckpoint).where(RegistrySyncCheckpoint.layer == layer, RegistrySyncCheckpoint.scope_key == key))
    if checkpoint is None:
        checkpoint = RegistrySyncCheckpoint(layer=layer, scope_key=key, status="running")
        session.add(checkpoint)
        session.commit()
    checkpoint.status = "running"
    session.commit()
    try:
        async for payload, total, index in client.iter_features(layer, bbox, teryt, checkpoint.next_start_index):
            checkpoint.total_expected = total
            features = payload.get("features", [])
            for feature in features:
                values = feature_values(layer, feature)
                if values:
                    upsert_feature(session, values)
            checkpoint.processed_count += len(features)
            checkpoint.next_start_index = index + len(features)
            if not features:
                checkpoint.status = "complete"
                checkpoint.completed_at = datetime.now(timezone.utc)
            session.commit()
        if checkpoint.status != "complete":
            checkpoint.status = "complete"
            checkpoint.completed_at = datetime.now(timezone.utc)
            session.commit()
    except GeoAzbestUnavailable as error:
        checkpoint.status = "source_unavailable"
        checkpoint.last_error = str(error)
        session.commit()
        raise
    return checkpoint
