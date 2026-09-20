from app.config import Settings
from app.fixtures.demo import DEMO_AREA
from app.providers.buildings import DemoBuildingProvider, OverpassBuildingProvider
from app.services.geo import validate_polygon


async def test_demo_provider_is_deterministic_and_spatially_filtered():
    records = await DemoBuildingProvider().fetch_buildings(validate_polygon(DEMO_AREA))
    assert [record.object_id for record in records] == ["100001", "100002", "100003"]


def test_relation_parser_preserves_multipolygon_hole():
    provider = OverpassBuildingProvider(Settings())
    ways = {
        "1": {"geometry": [{"lon": 21.0, "lat": 52.0}, {"lon": 21.002, "lat": 52.0}, {"lon": 21.002, "lat": 52.002}, {"lon": 21.0, "lat": 52.002}, {"lon": 21.0, "lat": 52.0}]},
        "2": {"geometry": [{"lon": 21.0005, "lat": 52.0005}, {"lon": 21.0015, "lat": 52.0005}, {"lon": 21.0015, "lat": 52.0015}, {"lon": 21.0005, "lat": 52.0015}, {"lon": 21.0005, "lat": 52.0005}]},
    }
    relation = {"members": [{"type": "way", "ref": 1, "role": "outer"}, {"type": "way", "ref": 2, "role": "inner"}]}
    geometry = provider._relation_geometry(relation, ways)
    assert geometry is not None
    assert len(geometry.interiors) == 1
