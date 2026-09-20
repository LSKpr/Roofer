import os
from uuid import uuid4

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Building

pytestmark = pytest.mark.skipif(not os.getenv("POSTGIS_TEST_DATABASE_URL"), reason="Set POSTGIS_TEST_DATABASE_URL to run PostGIS integration tests")


def test_postgis_round_trip_and_intersection():
    engine = create_engine(os.environ["POSTGIS_TEST_DATABASE_URL"])
    polygon = Polygon([(21.0, 52.0), (21.001, 52.0), (21.001, 52.001), (21.0, 52.001), (21.0, 52.0)])
    with Session(engine) as session:
        building = Building(source_provider="test", source_object_type="way", source_object_id=str(uuid4()), geometry=from_shape(polygon, srid=4326), osm_tags={})
        session.add(building)
        session.flush()
        count = session.scalar(select(func.count()).select_from(Building).where(func.ST_Intersects(Building.geometry, from_shape(polygon, srid=4326))))
        assert count >= 1
        session.rollback()
