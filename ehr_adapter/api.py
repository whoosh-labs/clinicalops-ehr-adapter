"""HTTP API. Called only by clinicalops-gateway-service (ClusterIP, no ingress).

Stateless: the upload is parsed in memory and nothing is stored. Logs carry source and counts only;
exception messages can contain patient data, so only exception types are logged.
"""

import json
import logging
import os
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ehr_adapter.normalize import PENDING_SOURCES, SOURCES, InputFormatError, normalize

log = logging.getLogger("ehr_adapter")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

MAX_FILE_BYTES = int(os.getenv("EHR_ADAPTER_MAX_FILE_MB", "25")) * 1024 * 1024

app = FastAPI(title="clinicalops-ehr-adapter")


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DroppedRow(_Camel):
    source: str
    patient_name: str
    reason: str


class Stats(_Camel):
    source_units: int
    rows: int
    dropped: int


class NormalizeResponse(_Camel):
    source: str
    csv: str
    row_count: int
    dropped: list[DroppedRow]
    stats: Stats
    warnings: list[str]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}


@app.get("/v1/sources")
def sources() -> list[str]:
    return sorted(SOURCES)


@app.post("/v1/normalize/{source}", response_model=NormalizeResponse, response_model_by_alias=True)
def normalize_upload(
    source: str,
    file: Annotated[UploadFile, File()],
    options: Annotated[str | None, Form()] = None,
) -> Any:
    source = source.strip().lower()
    if source in PENDING_SOURCES:
        raise HTTPException(status_code=422, detail=PENDING_SOURCES[source])
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source '{source}'")

    parsed_options = _parse_options(options)
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB")

    try:
        result = normalize(source, file.filename or "", content, parsed_options)
    except InputFormatError as exc:
        log.info("normalize source=%s rejected: input format", source)
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        log.error("normalize source=%s failed: %s", source, type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "failed to normalize the file"})

    log.info("normalize source=%s sourceUnits=%d rows=%d dropped=%d",
             source, result.source_units, len(result.rows), len(result.dropped))
    return NormalizeResponse(
        source=source,
        csv=result.to_csv(),
        row_count=len(result.rows),
        dropped=[DroppedRow(source=d.source, patient_name=d.patient_name, reason=d.reason) for d in result.dropped],
        stats=Stats(source_units=result.source_units, rows=len(result.rows), dropped=len(result.dropped)),
        warnings=result.warnings,
    )


def _parse_options(raw: str | None) -> dict[str, Any]:
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="options is not valid JSON") from None
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="options must be a JSON object")
    return value
