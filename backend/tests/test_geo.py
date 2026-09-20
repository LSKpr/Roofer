from shapely.geometry import MultiPolygon, Point, Polygon

from app.services.geo import area_km2, to_2180, to_4326, validate_polygon


def test_coordinate_round_trip_uses_polish_metric_crs():
    point = Point(21.0122, 52.2297)
    projected = to_2180(point)
    returned = to_4326(projected)
    assert 400000 < projected.x < 800000
    assert abs(returned.x - point.x) < 0.000001
    assert abs(returned.y - point.y) < 0.000001


def test_polygon_and_multipolygon_are_accepted_with_metric_area():
    exterior = [(21.0, 52.0), (21.001, 52.0), (21.001, 52.001), (21.0, 52.001), (21.0, 52.0)]
    hole = [(21.0002, 52.0002), (21.0008, 52.0002), (21.0008, 52.0008), (21.0002, 52.0008), (21.0002, 52.0002)]
    polygon = Polygon(exterior, [hole])
    multi = MultiPolygon([polygon])
    assert validate_polygon(polygon).interiors
    assert validate_polygon(multi).geoms[0].interiors
    assert 0 < area_km2(polygon) < 1
