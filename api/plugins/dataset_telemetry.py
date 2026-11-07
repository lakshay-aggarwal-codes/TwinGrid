"""Task 16: rack / sensor telemetry API for an imported research dataset (Danish AAU v5), served from the read-only bundle.

    GET /api/datasets/{dataset_id}                                      dataset record (attribution, window, racks, derived catalogue)
    GET /api/datasets/{dataset_id}/sensors                              sensor_list   (?measurand ?source_rack_id)
    GET /api/datasets/{dataset_id}/sensors/{sensor}/latest              latest        (?as_of_source_text, an exact label-second)
    GET /api/datasets/{dataset_id}/sensors/{sensor}/history             history       (?from_source_text ?to_source_text half-open,
                                                                          ?include_states ?include_invalid ?limit 1-1000 ?cursor)
    GET /api/datasets/{dataset_id}/racks/{source_rack_id}               rack_view     (?as_of_source_text); group power is a pointer
    GET /api/datasets/{dataset_id}/derived/{name}/latest | /history     the separate derived family (provenance derived)

Every request needs ``facility_id`` and ``stream=import:<dataset_id>``; there is no default and never ``live``. Order of
checks: rate limit -> signed-in user (401) -> demo token refused (403 ``dataset_not_available_to_demo``) -> bundle or
facility setting absent (404, identical to an unknown route) -> request parameters (contract error envelope).

Values come only from the read-only bundle (``DATASET_BUNDLE_PATH``; ``DATASET_FACILITY_ID`` is the facility id requests
must send). Nothing is written, filled, split per rack or converted to UTC. Source time is the naive label.
Dataset-domain failures use the contract's 8-key error envelope; framework failures stay problem+json.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from api.auth import get_current_user, get_token_claims, is_demo_claims
from api.errors import ApiError
from api.rate_limit import http_limit
from api.services import dataset_bundle_service as svc
from models.db_models import User
from src.dataset_bundle.errors import BundleError, BundleNotFound

logger = logging.getLogger(__name__)

DEMO_REFUSED_CODE = "dataset_not_available_to_demo"


async def dataset_gate(
    _user: Annotated[User, Depends(get_current_user)],
    claims: Annotated[dict, Depends(get_token_claims)],
) -> None:
    if is_demo_claims(claims):
        raise ApiError(403, DEMO_REFUSED_CODE, "Dataset telemetry is not available to demo sessions.")
    if not svc.bundle_available():
        raise ApiError(404, "not_found", "Not Found")


router = APIRouter(
    prefix="/api/datasets",
    tags=["dataset-telemetry"],
    dependencies=[Depends(http_limit("telemetry_read")), Depends(dataset_gate)],
)

_HEADERS = {"Cache-Control": "private, no-store"}
FacilityQ = Annotated[str | None, Query(description="Required. The facility id configured for this dataset.")]
StreamQ = Annotated[str | None, Query(description="Required. import:<dataset_id>; never live.")]
OptQ = Annotated[str | None, Query()]


def _json(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_HEADERS)


def _serve(facility_id: str | None, dataset_id: str, stream: str | None, build) -> JSONResponse:
    try:
        with svc.bundle() as conn:
            ctx = svc.make_ctx(conn, facility_id, dataset_id, stream)
            return _json(build(ctx))
    except svc.DatasetError as err:
        return _json(svc.error_envelope(err, facility_id, dataset_id, stream), err.status)
    except BundleNotFound:
        raise ApiError(404, "not_found", "Not Found") from None
    except BundleError:
        logger.error("dataset bundle unusable", exc_info=True)
        err = svc.DatasetError(500, "internal", "the dataset bundle is not usable")
        return _json(svc.error_envelope(err, facility_id, dataset_id, stream), 500)


@router.get(
    "/{dataset_id}", summary="Dataset record: attribution, modification statement, window, racks, derived catalogue"
)
def get_dataset(dataset_id: str, facility_id: FacilityQ = None, stream: StreamQ = None) -> JSONResponse:
    return _serve(facility_id, dataset_id, stream, svc.dataset_record)


@router.get("/{dataset_id}/sensors", summary="Measured sensors loaded in v1")
def get_sensors(
    dataset_id: str,
    facility_id: FacilityQ = None,
    stream: StreamQ = None,
    measurand: OptQ = None,
    source_rack_id: OptQ = None,
) -> JSONResponse:
    return _serve(facility_id, dataset_id, stream, lambda c: svc.sensor_list(c, measurand, source_rack_id))


@router.get("/{dataset_id}/sensors/{sensor}/latest", summary="Latest stored record of one measured sensor")
def get_sensor_latest(
    dataset_id: str, sensor: str, facility_id: FacilityQ = None, stream: StreamQ = None, as_of_source_text: OptQ = None
) -> JSONResponse:
    return _serve(facility_id, dataset_id, stream, lambda c: svc.latest(c, sensor, as_of_source_text, derived=False))


@router.get(
    "/{dataset_id}/sensors/{sensor}/history",
    summary="History of one measured sensor (source-text bounds, keyset paging)",
)
def get_sensor_history(
    dataset_id: str,
    sensor: str,
    facility_id: FacilityQ = None,
    stream: StreamQ = None,
    from_source_text: OptQ = None,
    to_source_text: OptQ = None,
    include_states: OptQ = None,
    include_invalid: OptQ = None,
    limit: OptQ = None,
    cursor: OptQ = None,
) -> JSONResponse:
    return _serve(
        facility_id,
        dataset_id,
        stream,
        lambda c: svc.history(
            c,
            sensor,
            derived=False,
            from_text=from_source_text,
            to_text=to_source_text,
            include_states=include_states,
            include_invalid=include_invalid,
            limit=limit,
            cursor=cursor,
        ),
    )


@router.get(
    "/{dataset_id}/racks/{source_rack_id}", summary="One rack: its temperature probes and its power attribution"
)
def get_rack(
    dataset_id: str,
    source_rack_id: str,
    facility_id: FacilityQ = None,
    stream: StreamQ = None,
    as_of_source_text: OptQ = None,
) -> JSONResponse:
    return _serve(facility_id, dataset_id, stream, lambda c: svc.rack_view(c, source_rack_id, as_of_source_text))


@router.get("/{dataset_id}/derived/{name}/latest", summary="Latest record of an approved derived series")
def get_derived_latest(
    dataset_id: str, name: str, facility_id: FacilityQ = None, stream: StreamQ = None, as_of_source_text: OptQ = None
) -> JSONResponse:
    return _serve(facility_id, dataset_id, stream, lambda c: svc.latest(c, name, as_of_source_text, derived=True))


@router.get("/{dataset_id}/derived/{name}/history", summary="History of an approved derived series")
def get_derived_history(
    dataset_id: str,
    name: str,
    facility_id: FacilityQ = None,
    stream: StreamQ = None,
    from_source_text: OptQ = None,
    to_source_text: OptQ = None,
    include_states: OptQ = None,
    include_invalid: OptQ = None,
    limit: OptQ = None,
    cursor: OptQ = None,
) -> JSONResponse:
    return _serve(
        facility_id,
        dataset_id,
        stream,
        lambda c: svc.history(
            c,
            name,
            derived=True,
            from_text=from_source_text,
            to_text=to_source_text,
            include_states=include_states,
            include_invalid=include_invalid,
            limit=limit,
            cursor=cursor,
        ),
    )
