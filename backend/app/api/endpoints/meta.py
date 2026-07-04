from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from app.core.geography import geography_meta_payload
from app.core.services import services_meta_payload


router = APIRouter()


class GeographyMetaResponse(BaseModel):
    regions: list[str]
    countries_by_region: dict[str, list[str]]
    central_asia_countries: list[str]


class ServiceMetaItem(BaseModel):
    value: str
    label: str


@router.get("/geography", response_model=GeographyMetaResponse)
async def get_geography_meta() -> GeographyMetaResponse:
    return GeographyMetaResponse.model_validate(geography_meta_payload())


@router.get("/services", response_model=list[ServiceMetaItem])
async def get_services_meta() -> list[ServiceMetaItem]:
    return [ServiceMetaItem.model_validate(item) for item in services_meta_payload()]
