from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.area import (
    MAX_AREA_KM2,
    MAX_LISTED_BUILDINGS,
    AreaScan,
    BoundingBox,
    area_problem,
    bbox_area_km2,
    bbox_problem,
    scan_area,
)
from app.area_analysis import (
    AreaAnalysis,
    analysis_from_model,
    corners,
    count_buildings,
    model_limit_problem,
    read_building_facts,
)
from app.prediction import (
    AREA_MODEL_MISSING,
    AREA_SERVICE_DOWN,
    MODEL_MAX_AREA_KM2,
    MODEL_MAX_BUILDINGS,
    ModelUnavailable,
    get_area_provider,
)

DATABASE_DOWN = "The database is not responding."

router = APIRouter(tags=["area"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Coordinates(Camel):
    lng: float = Field(ge=-180.0, le=180.0)
    lat: float = Field(ge=-90.0, le=90.0)


class ScanRequest(Camel):
    """Prostokat zaznaczony na mapie: naroznik polnocno-wschodni i poludniowo-zachodni."""

    ne: Coordinates
    sw: Coordinates


class Stats(Camel):
    """`not_listed` znaczy „nie ma go w rejestrze", a nie „dach jest czysty"."""

    total: int
    listed: int
    not_listed: int
    listed_share: float
    roof_area_m2: float
    listed_roof_area_m2: float
    registry_records: int


class ListedBuilding(Camel):
    id: int
    """`osm_id`, czyli ten sam adres, ktorym wola sie `/api/buildings/{id}` i ten sam, ktory niesie
    kafel. Ksztalt odpowiedzi jest bez zmian — zmienilo sie tylko znaczenie tej liczby."""
    area_m2: float
    centroid: Coordinates
    nr_dzialki: str | None = None


class ScanResponse(Camel):
    stats: Stats
    listed_buildings: list[ListedBuilding]
    truncated: bool
    area_km2: float


class ModelLimits(Camel):
    """Limity CUDZEGO API (100 budynkow, 4 km2), wystawione po to, zeby front ich nie zgadywal."""

    max_buildings: int
    max_area_km2: float


class AreaLimits(Camel):
    """Front pyta o limit, zamiast trzymac wlasna kopie liczby, ktora zna tylko backend.

    `maxAreaKm2` na wierzchu dotyczy skanu rejestru i sie nie zmienilo; `model` to osobny,
    ostrzejszy limit analizy modelem — te dwie liczby nie moga byc jedna zmienna po stronie frontu.
    """

    max_area_km2: float
    model: ModelLimits


class AnalysisStats(Camel):
    """Statystyki modelu dla prostokata.

    `suspected` znaczy „model widzi pokrycie wygladajace na eternit", nie „jest azbest" — dlatego
    obok licznikow jedzie `threshold` i `modelName`: da sie sprawdzic, co liczylo i od ktorej
    liczby. `noResult` to dachy bez oceny; nie sa czyste, sa nieznane, wiec nie wchodza do
    mianownika `suspectedShare`.
    """

    model_config = ConfigDict(protected_namespaces=())

    analysed: int
    no_result: int
    suspected: int
    suspected_share: float
    suspected_not_listed: int
    suspected_listed: int
    listed_not_suspected: int
    suspected_roof_area_m2: float
    threshold: float
    model_name: str
    unknown_to_us: int = 0
    """Ocenione przez model, a nieznane naszej bazie — poza wszystkimi licznikami powyzej.

    Powinno byc zerem (oba zrodla ida z tego samego snapshotu OSM). Niezerowe znaczy, ze snapshoty
    sie rozjechaly, i wtedy trzeba to zobaczyc, a nie doliczyc po cichu do „niezgloszonych"."""


class AnalysedBuildingOut(Camel):
    """`listed` pochodzi z naszego rejestru, `probability` i `geometry` od modelu."""

    id: int
    probability: float
    listed: bool
    area_m2: float
    geometry: dict[str, Any] | None = None


class AnalysisResponse(Camel):
    stats: AnalysisStats
    buildings: list[AnalysedBuildingOut]
    truncated: bool


def to_bounding_box(body: ScanRequest) -> BoundingBox:
    return BoundingBox(south=body.sw.lat, west=body.sw.lng, north=body.ne.lat, east=body.ne.lng)


def to_listed_building(item: dict[str, Any]) -> ListedBuilding:
    """Klucze przychodza z json_build_object w AREA_SCAN_SQL, wiec sa juz w camelCase."""
    return ListedBuilding(
        id=item["id"],
        area_m2=item["areaM2"],
        centroid=Coordinates(lng=item["lng"], lat=item["lat"]),
        nr_dzialki=item.get("nrDzialki"),
    )


def to_response(scan: AreaScan) -> ScanResponse:
    return ScanResponse(
        stats=Stats(
            total=scan.stats.total,
            listed=scan.stats.listed,
            not_listed=scan.stats.not_listed,
            listed_share=scan.stats.listed_share,
            roof_area_m2=scan.stats.roof_area_m2,
            listed_roof_area_m2=scan.stats.listed_roof_area_m2,
            registry_records=scan.stats.registry_records,
        ),
        listed_buildings=[to_listed_building(item) for item in scan.listed_buildings],
        truncated=scan.truncated,
        area_km2=scan.area_km2,
    )


def to_analysis_response(analysis: AreaAnalysis) -> AnalysisResponse:
    stats = analysis.stats
    return AnalysisResponse(
        stats=AnalysisStats(
            analysed=stats.analysed,
            no_result=stats.no_result,
            suspected=stats.suspected,
            suspected_share=stats.suspected_share,
            suspected_not_listed=stats.suspected_not_listed,
            suspected_listed=stats.suspected_listed,
            listed_not_suspected=stats.listed_not_suspected,
            suspected_roof_area_m2=stats.suspected_roof_area_m2,
            threshold=stats.threshold,
            model_name=stats.model_name,
            unknown_to_us=stats.unknown_to_us,
        ),
        buildings=[
            AnalysedBuildingOut(
                id=building.id,
                probability=building.probability,
                listed=building.listed,
                area_m2=building.area_m2,
                geometry=building.geometry,
            )
            for building in analysis.buildings
        ],
        truncated=analysis.truncated,
    )


def model_limits(settings: Any) -> tuple[int, float]:
    """Limity uruchomionej uslugi modelu. Jedno miejsce, z ktorego czytaja je bramka i endpoint
    limitow — inaczej front pokazywalby inna liczbe, niz blokuje backend."""
    return (
        int(getattr(settings, "prediction_model_max_buildings", MODEL_MAX_BUILDINGS)),
        float(getattr(settings, "prediction_model_max_area_km2", MODEL_MAX_AREA_KM2)),
    )


@router.get("/area/limits", response_model=AreaLimits)
async def limits(request: Request) -> AreaLimits:
    max_buildings, max_area_km2 = model_limits(request.app.state.settings)
    return AreaLimits(
        max_area_km2=MAX_AREA_KM2,
        model=ModelLimits(max_buildings=max_buildings, max_area_km2=max_area_km2),
    )


@router.post("/area/scan", response_model=ScanResponse, responses={400: {}, 503: {}})
async def scan(body: ScanRequest, request: Request) -> ScanResponse:
    bbox = to_bounding_box(body)
    problem = bbox_problem(bbox)
    if problem is not None:
        raise HTTPException(status_code=400, detail=problem)

    area_km2 = bbox_area_km2(bbox)
    too_large = area_problem(area_km2)
    if too_large is not None:  # bramka przed baza: za duzego zaznaczenia nawet nie odpytujemy
        raise HTTPException(status_code=400, detail=too_large)

    settings = request.app.state.settings
    try:
        result = await scan_area(request.app.state.pool, bbox, settings.database_timeout_s, MAX_LISTED_BUILDINGS)
    except Exception as error:  # padnieta baza to 503, nie 500 z tracebackiem
        raise HTTPException(status_code=503, detail=DATABASE_DOWN) from error
    return to_response(result)


@router.post("/area/analyze", response_model=AnalysisResponse, responses={400: {}, 503: {}})
async def analyze(body: ScanRequest, request: Request) -> AnalysisResponse:
    """Caly zaznaczony obszar przez model, zestawiony z rejestrem: `suspectedNotListed` to budynki,
    ktorych nikt nie zglosil, a model widzi na nich pokrycie wygladajace na eternit.

    Kolejnosc krokow jest bramka przed cudzym API: najpierw ksztalt prostokata, potem jego
    powierzchnia (bez bazy), potem liczba budynkow (jedno zapytanie), i dopiero na koncu model.
    Za duzy obszar dostaje wlasne 400 z liczbami, zamiast czekac kilka sekund na cudze 413.
    """
    bbox = to_bounding_box(body)
    problem = bbox_problem(bbox)
    if problem is not None:
        raise HTTPException(status_code=400, detail=problem)

    max_buildings, max_area_km2 = model_limits(request.app.state.settings)
    area_km2 = bbox_area_km2(bbox)
    too_large = model_limit_problem(area_km2, None, max_buildings, max_area_km2)
    if too_large is not None:  # sama powierzchnia: nie kosztuje ani bazy, ani modelu
        raise HTTPException(status_code=400, detail=too_large)

    provider = get_area_provider(request.app)
    if provider is None:
        # Atrapa nie liczy statystyk obszaru: szesc licznikow ze skrotow identyfikatorow
        # wygladaloby jak pomiar. Brak modelu to „nie wiemy", czyli 503 z komunikatem.
        raise HTTPException(status_code=503, detail=AREA_MODEL_MISSING)

    settings = request.app.state.settings
    pool = request.app.state.pool
    try:
        buildings = await count_buildings(pool, bbox, settings.database_timeout_s)
    except Exception as error:
        raise HTTPException(status_code=503, detail=DATABASE_DOWN) from error

    too_many = model_limit_problem(area_km2, buildings, max_buildings, max_area_km2)
    if too_many is not None:
        raise HTTPException(status_code=400, detail=too_many)

    try:
        result = await provider.analyze_area(corners(bbox))
    except ModelUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:  # padniety dostawca to 503, nigdy 500 i nigdy udawany wynik
        raise HTTPException(status_code=503, detail=AREA_SERVICE_DOWN) from error

    try:
        facts = await read_building_facts(
            pool,
            [building.osm_id for building in result.buildings if building.scored],
            settings.database_timeout_s,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail=DATABASE_DOWN) from error

    # Lista siega tyle, ile wpuscila bramka: `truncated` wylaczyloby w panelu suwak progu, bo bez
    # wszystkich ocen nie ma z czego przeliczac licznikow.
    return to_analysis_response(analysis_from_model(result, facts, max_buildings))
