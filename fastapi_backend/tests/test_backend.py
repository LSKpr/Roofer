from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from shapely.geometry import box, mapping

from fastapi_backend.app import create_app
from Data.build_roof_dataset import world_pixel
from fastapi_backend.database import Building, BuildingStore, TooManyBuildings, build_database
from fastapi_backend.imagery import ImageryError, SatelliteTiles
from fastapi_backend.inference import RoofModel
from fastapi_backend.schemas import AnalyzeRequest
from fastapi_backend.service import AnalysisService
from fastapi_backend.settings import Settings


class DatabaseTests(unittest.TestCase):
    def test_exact_intersection_not_centroid_or_bbox_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "buildings.geojson"
            hole = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}
            features = [
                {"type": "Feature", "id": "crossing", "properties": {"type": "house"}, "geometry": mapping(box(3, 1, 5, 3))},
                {"type": "Feature", "id": "courtyard", "properties": {}, "geometry": hole},
            ]
            source.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
            destination = root / "buildings.sqlite"
            build_database(source, destination)
            store = BuildingStore(destination)
            self.assertEqual(store.info["building_count"], 2)
            self.assertEqual(store.query((1.5, 1.5, 2.5, 2.5), 10), [])
            result = store.query((4.5, 1.5, 5.5, 2.5), 10)
            self.assertEqual([building.source_id for building in result], ["crossing"])
            with self.assertRaises(TooManyBuildings):
                store.query((0, 0, 6, 6), 1)
            with self.assertRaises(FileExistsError):
                build_database(source, destination)

    def test_invalid_features_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.geojson"
            source.write_text(json.dumps({"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": "ok", "properties": {}, "geometry": mapping(box(20, 52, 20.001, 52.001))},
                {"type": "Feature", "id": "bad", "properties": {}, "geometry": None},
            ]}))
            info = build_database(source, root / "buildings.sqlite")
            self.assertEqual(info["building_count"], 1)
            self.assertEqual(info["skipped_invalid"], 1)


class FakeStore:
    info = {"building_count": 2, "source": "fixture", "coverage_bbox": [20, 52, 21, 53]}

    def query(self, bbox, limit):
        return []


class FakeModel:
    model_id = "test-model"

    def predict(self, images):
        return [0.8] * len(images)


class FakeService:
    store = FakeStore()
    model = FakeModel()

    async def analyze(self, buildings):
        return []

    async def close(self):
        pass


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.token_path = Path(self.temporary.name) / "token"
        self.token = "test-token-not-a-real-secret-123456789"
        self.token_path.write_text(self.token)
        self.settings = replace(Settings(), token_file=self.token_path, cors_origins=("http://localhost:3000",))
        self.payload = {"south_west": {"longitude": 20, "latitude": 52}, "north_east": {"longitude": 20.001, "latitude": 52.001}}
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def client(self, service=None, settings=None):
        client = TestClient(create_app(settings or self.settings, service or FakeService()))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_health_and_authenticated_empty_geojson(self):
        client = self.client()
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.post("/v1/analyze", json=self.payload).status_code, 401)
        self.assertEqual(client.post("/v1/analyze", json=self.payload, headers={"Authorization": "Bearer wrong"}).status_code, 401)
        response = client.post("/v1/analyze", json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "FeatureCollection")
        self.assertEqual(response.json()["features"], [])
        self.assertEqual(response.json()["meta"]["matched"], 0)

    def test_coordinate_order_range_and_area_limits(self):
        client = self.client()
        for payload in (
            {**self.payload, "north_east": self.payload["south_west"]},
            {**self.payload, "south_west": {"longitude": 181, "latitude": 52}},
            {**self.payload, "south_west": {"longitude": 20, "latitude": 90}},
            {**self.payload, "unexpected": 1},
        ):
            self.assertEqual(client.post("/v1/analyze", json=payload, headers=self.headers).status_code, 422)
        large = {**self.payload, "north_east": {"longitude": 21, "latitude": 53}}
        self.assertEqual(client.post("/v1/analyze", json=large, headers=self.headers).status_code, 413)

    def test_nonfinite_coordinates_return_validation_error(self):
        response = self.client().post("/v1/analyze", content='{"south_west":{"longitude":NaN,"latitude":52},"north_east":{"longitude":21,"latitude":53}}', headers={**self.headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)

    def test_request_body_is_bounded(self):
        response = self.client().post("/v1/analyze", content=b"x" * 9000, headers=self.headers)
        self.assertEqual(response.status_code, 413)

    def test_cors_preflight(self):
        response = self.client().options("/v1/analyze", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:3000")

    def test_rate_limit(self):
        client = self.client(settings=replace(self.settings, requests_per_minute=1))
        self.assertEqual(client.post("/v1/analyze", json=self.payload, headers=self.headers).status_code, 200)
        self.assertEqual(client.post("/v1/analyze", json=self.payload, headers=self.headers).status_code, 429)

    def test_does_not_silently_truncate(self):
        service = FakeService()
        with patch.object(service.store, "query", side_effect=TooManyBuildings(100)):
            response = self.client(service).post("/v1/analyze", json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"]["code"], "TOO_MANY_BUILDINGS")

    def test_timeout(self):
        class SlowService(FakeService):
            async def analyze(self, buildings):
                await asyncio.sleep(1)
                return []
        client = self.client(SlowService(), replace(self.settings, request_timeout=0.01))
        self.assertEqual(client.post("/v1/analyze", json=self.payload, headers=self.headers).status_code, 504)


class ImageryTests(unittest.IsolatedAsyncioTestCase):
    async def test_nine_tiles_and_building_center_not_tile_center(self):
        calls = []

        def handle(request):
            calls.append(request)
            x, y = int(request.url.params["x"]), int(request.url.params["y"])
            stream = io.BytesIO()
            Image.new("RGB", (256, 256), (x, y, 128)).save(stream, format="PNG")
            return httpx.Response(200, content=stream.getvalue())

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        tiles = SatelliteTiles(Settings(), client=client)
        with patch("fastapi_backend.imagery.world_pixel", return_value=(10 * 256 + 7, 20 * 256 + 250)):
            image, origin = await tiles.crop(20, 52)
            await tiles.crop(20, 52)
        self.assertEqual(len(calls), 9)
        self.assertTrue(all(request.url.params["z"] == "20" and request.url.params["lyrs"] == "s" for request in calls))
        self.assertEqual(image.size, (128, 128))
        self.assertEqual(image.getpixel((0, 0)), (9, 20, 128))
        self.assertEqual(image.getpixel((127, 127)), (10, 21, 128))
        self.assertEqual(origin, (2503, 5306))
        await tiles.close()

    async def test_bad_tile_returns_error_not_black_image(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
        tiles = SatelliteTiles(Settings(), client=client)
        with self.assertRaises(ImageryError):
            await tiles.crop(20, 52)
        await tiles.close()

    async def test_concurrent_tile_requests_are_deduplicated(self):
        count = 0
        stream = io.BytesIO()
        Image.new("RGB", (256, 256)).save(stream, format="PNG")

        async def handle(request):
            nonlocal count
            count += 1
            await asyncio.sleep(0.01)
            return httpx.Response(200, content=stream.getvalue())

        tiles = SatelliteTiles(Settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        results = await asyncio.gather(*(tiles.tile(10, 20) for _ in range(10)))
        self.assertEqual(count, 1)
        self.assertEqual(len(results), 10)
        await tiles.close()


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_polygon_is_returned_and_failures_have_null_scores(self):
        class Tiles:
            async def crop(self, longitude, latitude):
                if longitude > 20.003:
                    raise ImageryError("SATELLITE_UNAVAILABLE")
                if longitude > 20.001:
                    image = Image.new("RGB", (128, 128), (40, 100, 30))
                else:
                    y, x = np.indices((128, 128))
                    image = Image.fromarray((80 + ((x // 4 + y // 8) % 2) * 60).astype(np.uint8)).convert("RGB")
                x, y = world_pixel(longitude, latitude, 20)
                return image, (round(x - 64), round(y - 64))

            async def close(self):
                pass

        buildings = [Building(index, str(index), "house", box(20 + index * 0.002, 52, 20.0001 + index * 0.002, 52.0001)) for index in range(3)]
        service = AnalysisService(Settings(), store=FakeStore(), model=FakeModel(), tiles=Tiles())
        try:
            results = await service.analyze(buildings)
        finally:
            await service.close()
        self.assertEqual(len(results), 3)
        self.assertEqual([result.properties.status for result in results], ["ok", "low_quality", "imagery_error"])
        self.assertEqual([result.properties.asbestos_probability for result in results], [0.8, None, None])
        self.assertEqual(results[0].properties.quality["region_source"], "footprint")
        self.assertEqual(results[2].properties.reasons, ["SATELLITE_UNAVAILABLE"])


class InferenceTests(unittest.TestCase):
    def test_preprocessing_and_softmax_order(self):
        model = RoofModel.__new__(RoofModel)
        model.mean = np.array([0.3616, 0.3497, 0.3882], dtype=np.float32).reshape(1, 3, 1, 1)
        model.std = np.array([0.2406, 0.2315, 0.2276], dtype=np.float32).reshape(1, 3, 1, 1)

        class Session:
            def run(self, outputs, inputs):
                array = inputs["images"]
                self_input.append(array)
                return [np.array([[1000, 1001], [1002, 1000]], dtype=np.float32)]
        self_input = []
        model.session = Session()
        result = model.predict([Image.new("RGB", (128, 128), (255, 128, 0))] * 2)
        self.assertEqual(self_input[0].shape, (2, 3, 128, 128))
        self.assertEqual(self_input[0].dtype, np.float32)
        np.testing.assert_allclose(self_input[0][0, :, 0, 0], (np.array([1, 128 / 255, 0]) - model.mean.ravel()) / model.std.ravel(), rtol=1e-6)
        self.assertAlmostEqual(result[0], 0.7310586, places=6)
        self.assertAlmostEqual(result[1], 0.1192029, places=6)

    def test_bad_images_are_not_resized(self):
        model = RoofModel.__new__(RoofModel)
        with self.assertRaises(ValueError):
            model.predict([Image.new("RGB", (256, 256))])


if __name__ == "__main__":
    unittest.main()
