import pytest

from app.snapshots import SnapshotError, iter_features, parse_footer, parse_header

HEADER = '{"type":"FeatureCollection","name":"test","features":['
FEATURE = '{"type":"Feature","id":"a","geometry":null,"properties":{}}'


def snapshot(features: list[str], declared: int | None = None) -> list[str]:
    body = [f"{feature}," for feature in features[:-1]] + features[-1:]
    footer = "]}" if declared is None else f'],"numberReturned":{declared}}}'
    return [HEADER, *body, footer]


def test_header_gives_access_to_snapshot_metadata() -> None:
    assert parse_header(HEADER)["name"] == "test"


def test_header_without_the_features_marker_is_rejected() -> None:
    with pytest.raises(SnapshotError, match="format sie zmienil"):
        parse_header('{"type":"FeatureCollection","features":[]}')


def test_footer_reads_the_declared_count_next_to_other_keys() -> None:
    assert parse_footer('],"numberMatched":3,"numberReturned":2}') == 2


def test_footer_without_a_count_is_allowed() -> None:
    assert parse_footer("]}") is None


def test_footer_with_a_non_integer_count_is_rejected() -> None:
    with pytest.raises(SnapshotError, match="liczba calkowita"):
        parse_footer('],"numberReturned":"2"}')


def test_features_come_back_without_the_trailing_comma() -> None:
    assert list(iter_features(snapshot([FEATURE, FEATURE], declared=2))) == [FEATURE, FEATURE]


def test_blank_lines_are_ignored() -> None:
    lines = [HEADER, f"{FEATURE},", "", FEATURE, "", '],"numberReturned":2}']

    assert len(list(iter_features(lines))) == 2


def test_declared_count_that_does_not_match_is_an_error() -> None:
    with pytest.raises(SnapshotError, match="deklaruje 5 obiektow, a zawiera 2"):
        list(iter_features(snapshot([FEATURE, FEATURE], declared=5)))


def test_a_truncated_file_is_an_error() -> None:
    with pytest.raises(SnapshotError, match="obciety"):
        list(iter_features([HEADER, f"{FEATURE},", FEATURE]))


def test_an_empty_file_is_an_error() -> None:
    with pytest.raises(SnapshotError, match="pusty"):
        list(iter_features([]))


def test_stopping_early_does_not_verify_the_count() -> None:
    features = iter_features(snapshot([FEATURE, FEATURE], declared=5))

    assert next(features) == FEATURE
