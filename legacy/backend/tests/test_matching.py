from shapely.geometry import Polygon

from app.services.matching import BuildingCandidate, RegistryCandidate, aggregate_status, match_building, overlap_metrics


def square(left: float, bottom: float, right: float, top: float) -> Polygon:
    return Polygon([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)])


def test_location_match_is_validated_by_intersection_and_scored():
    building = BuildingCandidate("building", square(21.0, 52.0, 21.001, 52.001), {"geoazbest:location_id": "loc-1"})
    record = RegistryCandidate("record", square(21.0001, 52.0001, 21.0009, 52.0009), "loc-1", "12/4", "listed")
    decisions = match_building(building, [record])
    assert len(decisions) == 1
    assert decisions[0].match_method == "location_id_spatial"
    assert decisions[0].confidence == 0.99
    assert 0 < decisions[0].overlap_ratio < 1


def test_conflicting_records_remain_ambiguous():
    building = BuildingCandidate("building", square(21.0, 52.0, 21.001, 52.001), {})
    listed = RegistryCandidate("listed", square(21.0, 52.0, 21.001, 52.001), None, None, "listed")
    cleaned = RegistryCandidate("cleaned", square(21.0, 52.0, 21.001, 52.001), None, None, "cleaned")
    decisions = match_building(building, [listed, cleaned])
    assert len(decisions) == 2
    assert all(decision.ambiguity_flag for decision in decisions)
    assert aggregate_status(decisions, {"listed": listed, "cleaned": cleaned}, True) == "ambiguous"


def test_unavailable_registry_never_becomes_not_listed():
    assert aggregate_status([], {}, False) == "unknown"


def test_overlap_is_calculated_in_square_metres():
    area, ratio = overlap_metrics(square(21.0, 52.0, 21.001, 52.001), square(21.0005, 52.0, 21.0015, 52.001))
    assert area > 1000
    assert 0.45 < ratio < 0.55
