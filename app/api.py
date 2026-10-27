"""HTTP API for the processed Lubbock crash extract."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.cleaning import SEVERITY_LABELS, SEVERITY_ORDER
from app.database import connect, read_metadata
from app.metrics import (
    GRAINS,
    FilterError,
    crash_total,
    filter_choices,
    locations,
    parse_filters,
    severity_counts,
    top_factors,
    trends,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PACKAGE_ROOT / "static"

app = FastAPI(
    title="Lubbock District Crash Analytics",
    summary="Crash-level injury and fatal crash figures from a TxDOT CRIS extract.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_connection():
    try:
        connection = connect()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        yield connection
    finally:
        connection.close()


@app.get("/health")
def health(connection=Depends(get_connection)):
    metadata = read_metadata(connection)
    crash_count = metadata.get("crash_count")
    if crash_count is None:
        crash_count = connection.execute("SELECT COUNT(*) FROM crashes").fetchone()[0]
    return {
        "status": "ok",
        "crashes": int(crash_count),
        "district": metadata.get("district"),
        "source_as_of": metadata.get("source_as_of"),
    }


@app.get("/api/filters")
def filters(connection=Depends(get_connection)):
    """Values the dashboard uses to fill its filter lists."""
    payload = filter_choices(connection)
    payload["source"] = _source(connection)
    return payload


@app.get("/api/severity")
def severity(
    county: str | None = None,
    year: int | None = Query(default=None, ge=1900, le=2100),
    severity: str | None = None,
    road_class: str | None = None,
    output_format: str = Query(default="json", alias="format"),
    connection=Depends(get_connection),
):
    """Crash counts by KABCO injury severity."""
    chosen = _filters(county, year, severity, road_class)
    total, _deaths = crash_total(connection, chosen)
    rows = severity_counts(connection, chosen)
    payload = {
        "filters": chosen.as_dict(),
        "crash_count": total,
        "counts": rows,
    }
    csv_response = _csv(
        output_format,
        "severity.csv",
        ["severity", "label", "count", "share"],
        rows,
    )
    return csv_response or payload


@app.get("/api/factors")
def factors(
    county: str | None = None,
    year: int | None = Query(default=None, ge=1900, le=2100),
    severity: str | None = None,
    road_class: str | None = None,
    limit: int = Query(default=5, ge=1, le=50),
    output_format: str = Query(default="json", alias="format"),
    connection=Depends(get_connection),
):
    """Most frequent contributing factors.

    The rank counts crashes, not person rows. A crash listing two factors
    is counted once for each. NONE and blank values are omitted.
    """
    chosen = _filters(county, year, severity, road_class)
    total, _deaths = crash_total(connection, chosen)
    rows = top_factors(connection, chosen, limit=limit)
    payload = {
        "filters": chosen.as_dict(),
        "crash_count": total,
        "limit": limit,
        "factors": rows,
    }
    csv_response = _csv(
        output_format,
        "factors.csv",
        ["rank", "factor", "count", "share"],
        rows,
    )
    return csv_response or payload


@app.get("/api/trends")
def trend(
    county: str | None = None,
    year: int | None = Query(default=None, ge=1900, le=2100),
    severity: str | None = None,
    road_class: str | None = None,
    grain: str = "month",
    output_format: str = Query(default="json", alias="format"),
    connection=Depends(get_connection),
):
    """Crash counts over month, year, or hour of day."""
    chosen = _filters(county, year, severity, road_class)
    if grain not in GRAINS:
        raise HTTPException(
            status_code=400, detail="grain must be one of month, year, hour."
        )
    rows = trends(connection, chosen, grain=grain)
    payload = {
        "filters": chosen.as_dict(),
        "grain": grain,
        "points": rows,
    }
    fieldnames = list(rows[0].keys()) if rows else ["period", "count"]
    csv_response = _csv(output_format, f"trends-{grain}.csv", fieldnames, rows)
    return csv_response or payload


@app.get("/api/locations")
def crash_locations(
    county: str | None = None,
    year: int | None = Query(default=None, ge=1900, le=2100),
    severity: str | None = None,
    road_class: str | None = None,
    limit: int = Query(default=25000, ge=1, le=30000),
    connection=Depends(get_connection),
):
    """Crash coordinates for the map. Crashes without a usable point are omitted."""
    chosen = _filters(county, year, severity, road_class)
    payload = locations(connection, chosen, limit=limit)
    payload["filters"] = chosen.as_dict()
    return payload


@app.get("/api/overview")
def overview(
    county: str | None = None,
    year: int | None = Query(default=None, ge=1900, le=2100),
    severity: str | None = None,
    road_class: str | None = None,
    connection=Depends(get_connection),
):
    """Severity, top factors, monthly trend, and hour of day in one response."""
    chosen = _filters(county, year, severity, road_class)
    total, deaths = crash_total(connection, chosen)
    return {
        "filters": chosen.as_dict(),
        "source": _source(connection),
        "crash_count": total,
        "death_count": deaths,
        "severity": severity_counts(connection, chosen),
        "factors": top_factors(connection, chosen, limit=5),
        "trends": trends(connection, chosen, grain="month"),
        "hours": trends(connection, chosen, grain="hour"),
    }


@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _filters(
    county: str | None,
    year: int | None,
    severity: str | None,
    road_class: str | None,
):
    try:
        return parse_filters(county, year, severity, road_class)
    except FilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _source(connection) -> dict:
    metadata = read_metadata(connection)
    return {
        "district": metadata.get("district"),
        "as_of": metadata.get("source_as_of"),
        "person_rows": _maybe_int(metadata.get("person_rows")),
        "severities": [
            {"code": code, "label": SEVERITY_LABELS[code]} for code in SEVERITY_ORDER
        ],
    }


def _maybe_int(value: str | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _csv(output_format: str, filename: str, fieldnames: list[str], rows: list[dict]):
    if output_format == "json":
        return None
    if output_format != "csv":
        raise HTTPException(status_code=400, detail="format must be json or csv.")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
