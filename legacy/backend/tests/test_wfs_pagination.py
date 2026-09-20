import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.providers.geoazbest import GeoAzbestUnavailable, GeoAzbestWfsClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_wfs_uses_start_index_and_consumes_fixture_pages():
    pages = {"0": json.loads((FIXTURES / "wfs-page-1.json").read_text()), "2": json.loads((FIXTURES / "wfs-page-2.json").read_text())}

    def handler(request: httpx.Request) -> httpx.Response:
        index = request.url.params.get("startIndex", "0")
        return httpx.Response(200, json=pages[index])

    settings = Settings(geoazbest_wfs_url="https://example.test/wfs", wfs_page_size=2)
    client = GeoAzbestWfsClient(settings, httpx.MockTransport(handler))
    pages_seen = [payload async for payload in client.iter_features("wfs:budynki_z_azbestem")]
    assert [item[2] for item in pages_seen] == [0, 2]
    assert sum(len(item[0]["features"]) for item in pages_seen) == 3


@pytest.mark.asyncio
async def test_wfs_failure_is_explicit_source_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = GeoAzbestWfsClient(Settings(geoazbest_wfs_url="https://example.test/wfs"), httpx.MockTransport(handler))
    with pytest.raises(GeoAzbestUnavailable):
        async for _ in client.iter_features("wfs:budynki_z_azbestem"):
            pass
