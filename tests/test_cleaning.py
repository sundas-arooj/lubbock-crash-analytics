"""Checks for the crash-level cleaning rules."""

from pathlib import Path

from app.cleaning import load_export, parse_factors
from app.database import write_database
from app.metrics import parse_filters, trends

FIXTURE = Path(__file__).parent / "fixtures" / "mini_crashes.csv"


def test_preamble_is_skipped_and_person_rows_collapse():
    export = load_export(FIXTURE)
    assert export.person_rows == 5
    assert len(export.crashes) == 4
    assert export.district == "LUBBOCK"
    assert export.source_as_of == "2026-10-22"
    assert [crash.crash_id for crash in export.crashes] == ["100", "200", "300", "400"]


def test_severity_county_and_factors_are_normalized():
    crashes = {crash.crash_id: crash for crash in load_export(FIXTURE).crashes}
    assert crashes["100"].severity == "B"
    assert crashes["100"].county == "LUBBOCK"
    assert crashes["100"].road_class == "CITY STREET"
    assert crashes["100"].factors == ("FAILED TO CONTROL SPEED",)
    assert crashes["100"].crash_hour == 8
    assert crashes["100"].death_count == 0
    assert crashes["200"].death_count == 2
    assert crashes["200"].factors == (
        "UNSAFE SPEED",
        "UNDER INFLUENCE - ALCOHOL",
    )
    assert crashes["300"].factors == ()
    assert crashes["300"].latitude is None
    assert crashes["300"].crash_hour == 0
    assert crashes["400"].crash_hour is None
    assert crashes["400"].latitude is None
    assert crashes["400"].factors == ("DRIVER INATTENTION",)
    assert crashes["400"].crash_month == 7


def test_none_and_duplicates_are_dropped_from_factors():
    assert parse_factors(
        "FAILED TO CONTROL SPEED; NONE; failed to control speed"
    ) == ("FAILED TO CONTROL SPEED",)
    assert parse_factors("No Data") == ()
    assert parse_factors(None) == ()


def test_monthly_trend_fills_gaps_inside_the_observed_span(tmp_path):
    export = load_export(FIXTURE)
    db_path = write_database(export, tmp_path / "crashes.db")
    from app.database import connect

    connection = connect(db_path)
    try:
        points = trends(connection, parse_filters(), grain="month")
    finally:
        connection.close()
    by_period = {point["period"]: point["count"] for point in points}
    assert by_period["2020-01"] == 1
    assert by_period["2020-02"] == 0
    assert by_period["2020-07"] == 1
    assert "2019-12" not in by_period
    assert points[-1]["period"] == "2022-03"
