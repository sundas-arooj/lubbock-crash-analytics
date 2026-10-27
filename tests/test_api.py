"""HTTP checks against the small fixture extract."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.cleaning import load_export
from app.database import write_database

FIXTURE = Path(__file__).parent / "fixtures" / "mini_crashes.csv"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = write_database(load_export(FIXTURE), tmp_path / "crashes.db")
    monkeypatch.setenv("CRASH_DB_PATH", str(db_path))
    return TestClient(app)


def test_missing_database_is_a_service_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CRASH_DB_PATH", str(tmp_path / "absent.db"))
    response = TestClient(app).get("/health")
    assert response.status_code == 503


def test_health_and_dashboard(client):
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["crashes"] == 4
    assert body["district"] == "LUBBOCK"
    assert body["source_as_of"] == "2026-10-22"
    page = client.get("/")
    assert page.status_code == 200
    assert "Crash profile" in page.text


def test_severity_counts_are_crash_level(client):
    body = client.get("/api/severity").json()
    assert body["crash_count"] == 4
    counts = {item["severity"]: item["count"] for item in body["counts"]}
    assert counts == {"K": 1, "A": 1, "B": 1, "C": 1}
    filtered = client.get("/api/severity", params={"county": "lubbock"}).json()
    assert filtered["crash_count"] == 2
    by_code = {item["severity"]: item["count"] for item in filtered["counts"]}
    assert by_code["B"] == 1
    assert by_code["C"] == 1
    assert by_code["K"] == 0


def test_factors_drop_none_and_accept_a_severity_filter(client):
    body = client.get("/api/factors").json()
    names = [item["factor"] for item in body["factors"]]
    assert "NONE" not in names
    assert "NO DATA" not in names
    assert names[0] == "DRIVER INATTENTION"
    fatal = client.get("/api/factors", params={"severity": "K"}).json()
    assert fatal["crash_count"] == 1
    assert [item["factor"] for item in fatal["factors"]] == [
        "UNDER INFLUENCE - ALCOHOL",
        "UNSAFE SPEED",
    ]


def test_trends_and_locations(client):
    hours = client.get("/api/trends", params={"grain": "hour"}).json()["points"]
    assert len(hours) == 24
    assert hours[0]["count"] == 1
    assert hours[8]["count"] == 1
    assert hours[23]["count"] == 1
    mapped = client.get("/api/locations").json()
    assert mapped["crash_count"] == 4
    assert mapped["returned"] == 2
    assert {point["crash_id"] for point in mapped["locations"]} == {"100", "200"}


def test_overview_keeps_deaths_separate_from_fatal_crashes(client):
    body = client.get("/api/overview").json()
    assert body["death_count"] == 2
    fatal = next(item for item in body["severity"] if item["severity"] == "K")
    assert fatal["count"] == 1
    assert len(body["factors"]) == 4
    assert body["hours"][8]["count"] == 1


def test_csv_and_rejected_filters(client):
    csv_response = client.get("/api/severity", params={"format": "csv"})
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "Fatal injury" in csv_response.text
    assert client.get("/api/severity", params={"severity": "Z"}).status_code == 400
    assert client.get("/api/trends", params={"grain": "week"}).status_code == 400
    assert client.get("/api/factors", params={"format": "xml"}).status_code == 400


def test_filter_lists(client):
    body = client.get("/api/filters").json()
    assert body["counties"] == ["HALE", "LUBBOCK", "TERRY"]
    assert body["years"] == [2020, 2021, 2022]
    assert "CITY STREET" in body["road_classes"]
    assert [item["code"] for item in body["severities"]] == ["K", "A", "B", "C"]
