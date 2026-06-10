"""FastAPI service.

Two endpoints — single and batch — both return the same FindingPacket shape.
The app also serves the static frontend, so the whole prototype is one
deployable unit at one URL.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import rules_engine as rules
from .extraction import Extractor, get_extractor
from .models import ApplicationRecord, FindingPacket

app = FastAPI(title="TTB Label Verification", version="0.1.0")

_STATIC = Path(__file__).parent / "static"

# The extractor is built once at startup. If the vision SDK/key is missing it
# stays None and /verify reports a clean 503 instead of crashing.
_extractor: Extractor | None = None


@app.on_event("startup")
def _startup() -> None:
    global _extractor
    try:
        _extractor = get_extractor()
    except Exception:  # noqa: BLE001 — surface as a clear runtime error, don't die
        _extractor = None


def _record_from_form(
    brand_name: str, class_type: str, alcohol_content: str,
    net_contents: str, producer_name_address: str, country_of_origin: str,
) -> ApplicationRecord:
    return ApplicationRecord(
        brand_name=brand_name, class_type=class_type,
        alcohol_content=alcohol_content, net_contents=net_contents,
        producer_name_address=producer_name_address,
        country_of_origin=country_of_origin,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "extractor": _extractor.name if _extractor else None}


@app.post("/verify", response_model=FindingPacket)
async def verify(
    label: UploadFile = File(...),
    brand_name: str = Form(""),
    class_type: str = Form(""),
    alcohol_content: str = Form(""),
    net_contents: str = Form(""),
    producer_name_address: str = Form(""),
    country_of_origin: str = Form(""),
) -> FindingPacket:
    if _extractor is None:
        raise HTTPException(503, "No extractor available. Set EXTRACTOR/credentials.")
    record = _record_from_form(brand_name, class_type, alcohol_content,
                               net_contents, producer_name_address, country_of_origin)
    image = await label.read()
    t0 = time.perf_counter()
    try:
        extracted = _extractor.extract(image, label.content_type or "image/jpeg")
    except ValueError:
        raise HTTPException(422, "The label couldn't be read cleanly. Try a sharper, straight-on photo.")
    return rules.build_packet(record, extracted, time.perf_counter() - t0, _extractor.name)


@app.post("/verify-batch")
async def verify_batch(
    labels: list[UploadFile] = File(...),
    brand_name: str = Form(""),
    class_type: str = Form(""),
    alcohol_content: str = Form(""),
    net_contents: str = Form(""),
    producer_name_address: str = Form(""),
    country_of_origin: str = Form(""),
) -> dict:
    if _extractor is None:
        raise HTTPException(503, "No extractor available. Set EXTRACTOR/credentials.")
    record = _record_from_form(brand_name, class_type, alcohol_content,
                               net_contents, producer_name_address, country_of_origin)
    results = []
    t0 = time.perf_counter()
    for f in labels:
        image = await f.read()
        try:
            extracted = _extractor.extract(image, f.content_type or "image/jpeg")
            packet = rules.build_packet(record, extracted, 0.0, _extractor.name)
            results.append({"filename": f.filename, "verdict": packet.verdict, "findings": packet.findings})
        except Exception:  # noqa: BLE001 — one bad label shouldn't sink the batch
            results.append({"filename": f.filename, "verdict": None, "error": "unreadable"})
    return {"count": len(results), "elapsed_seconds": round(time.perf_counter() - t0, 2), "results": results}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
