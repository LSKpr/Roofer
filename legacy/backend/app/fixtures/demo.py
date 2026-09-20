from typing import Any

DEMO_AREA = {
    "type": "Polygon",
    "coordinates": [[[21.0077, 52.2282], [21.0113, 52.2282], [21.0113, 52.2308], [21.0077, 52.2308], [21.0077, 52.2282]]],
}


def polygon(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat]]],
    }


DEMO_BUILDINGS = [
    {"id": "100001", "type": "way", "tags": {"building": "residential", "addr:street": "Demo Street", "addr:housenumber": "10", "geoazbest:location_id": "demo-location-1", "nr_dzialki": "12/4"}, "geometry": polygon(21.0080, 52.2285, 21.0086, 52.2290)},
    {"id": "100002", "type": "way", "tags": {"building": "house", "addr:street": "Demo Street", "addr:housenumber": "12", "geoazbest:location_id": "demo-location-2", "nr_dzialki": "12/5"}, "geometry": polygon(21.0090, 52.2285, 21.0096, 52.2290)},
    {"id": "100003", "type": "relation", "tags": {"building": "apartments", "name": "Unknown registry status example"}, "geometry": polygon(21.0100, 52.2294, 21.0109, 52.2303)},
]

DEMO_REGISTRY = [
    {"id": "wfs:budynki_z_azbestem.demo-1", "layer": "wfs:budynki_z_azbestem", "status": "listed", "location_id": "demo-location-1", "parcel_number": "12/4", "teryt": "1465011", "geometry": polygon(21.00802, 52.22852, 21.00858, 52.22898), "properties": {"id_lok": "demo-location-1", "nr_dzialki": "12/4", "stopien_pilnosci": "1", "stopien_pilnosci_opis": "Urgent", "ilosc_wyrobu": 1200.0, "planowany_rok_unieszkodliwienia_wyrobu": 2027}},
    {"id": "wfs:budynki_oczyszczone.demo-2", "layer": "wfs:budynki_oczyszczone", "status": "cleaned", "location_id": "demo-location-2", "parcel_number": "12/5", "teryt": "1465011", "geometry": polygon(21.00902, 52.22852, 21.00958, 52.22898), "properties": {"id_lok": "demo-location-2", "nr_dzialki": "12/5", "stopien_pilnosci": "3", "ilosc_wyrobu": 900.0, "ilosc_przekazana_do_unieszkodliwienia": 900.0, "rok_unieszkodliwienia_wyrobu": 2021}},
]
