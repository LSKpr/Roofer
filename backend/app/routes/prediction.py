from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.prediction import (
    PROVIDER_ERROR_NOTE,
    RoofAnalysis,
    Source,
    Verdict,
    get_provider,
    read_building_shape,
    unavailable_analysis,
)

router = APIRouter(tags=["prediction"])


class Camel(BaseModel):
    # `protected_namespaces=()`, bo pole nazywa sie `model_name` (w JSON `modelName`), a pydantic
    # domyslnie ostrzega przed polami z przedrostkiem `model_`. Nazwa jest czescia ustalonego
    # kontraktu odpowiedzi, wiec zmienia sie ustawienie, nie nazwe.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, protected_namespaces=())


class RoofAnalysisResponse(Camel):
    """Ocena pokrycia dachu.

    `source="mock"` razem z `modelName=null` znaczy, ze zadnego modelu nie bylo — to wynik
    demonstracyjny i `note` mowi to wprost. `probability=null` znaczy „nie wiemy", nigdy
    „sprawdzone i nie widac eternitu"; do tego sluzy dopiero liczba 0.0.
    """

    source: Source
    verdict: Verdict
    probability: float | None = None
    model_name: str | None = None
    note: str


def to_response(analysis: RoofAnalysis) -> RoofAnalysisResponse:
    return RoofAnalysisResponse(
        source=analysis.source,
        verdict=analysis.verdict,
        probability=analysis.probability,
        model_name=analysis.model_name,
        note=analysis.note,
    )


@router.get(
    "/buildings/{osm_id}/analysis",
    response_model=RoofAnalysisResponse,
    responses={404: {}, 503: {}},
)
async def analysis(osm_id: int, request: Request) -> RoofAnalysisResponse:
    """Budynek wskazuje `osm_id`, wiec werdykt atrapy dla tego samego dachu nie zmienia sie po
    ponownym imporcie — przy kluczu z sekwencji zmienial sie za kazdym razem."""
    settings = request.app.state.settings
    try:
        shape = await read_building_shape(request.app.state.pool, osm_id, settings.database_timeout_s)
    except Exception as error:  # padnieta baza to 503, nie 500 z tracebackiem
        raise HTTPException(status_code=503, detail="The database is not responding.") from error
    if shape is None:
        raise HTTPException(status_code=404, detail="There is no building with this identifier.")

    provider = get_provider(request.app)
    try:
        result = await provider.analyze(shape)
    except Exception:
        # Padniety dostawca oceny nie moze zabrac karty budynku ani udawac wyniku: oddajemy
        # „nie wiemy" z probability=null, zgodnie z zasada, ze kazde zewnetrzne zrodlo ma stan nieznany.
        result = unavailable_analysis(PROVIDER_ERROR_NOTE)
    return to_response(result)
