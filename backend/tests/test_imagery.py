from app.main import descriptor_by_id
from app.providers.imagery import GUGIK_WMS_CURRENT, GUGIK_WMS_CURRENT_DETAIL, tile_request_candidates, wms_tile_parameters


def test_gugik_uses_technical_wms_layer_names():
    current = descriptor_by_id("gugik-ortho-current")
    historical = descriptor_by_id("gugik-ortho-2021")
    assert current.layer_id == "Raster"
    assert current.service_configuration["layers"] == "Raster"
    assert historical.layer_id == "Raster"
    assert historical.service_configuration["layers"] == "Raster"
    _, current_params = wms_tile_parameters(current, 7, 70, 42)
    _, historical_params = wms_tile_parameters(historical, 17, 73184, 43159)
    assert current_params["LAYERS"] == "Raster"
    assert historical_params["LAYERS"] == "Raster"
    assert historical_params["TIME"] == "2021-01-01T00:00:00.000Z"


def test_wide_zoom_uses_nationwide_service_and_deep_zoom_prefers_detail():
    current = descriptor_by_id("gugik-ortho-current")
    wide = tile_request_candidates(current, 7, 70, 42)
    deep = tile_request_candidates(current, 17, 73185, 43159)
    assert [url for url, _ in wide] == [GUGIK_WMS_CURRENT, GUGIK_WMS_CURRENT_DETAIL]
    assert [url for url, _ in deep] == [GUGIK_WMS_CURRENT_DETAIL, GUGIK_WMS_CURRENT]
    assert all(params["LAYERS"] == "Raster" for _, params in deep)
