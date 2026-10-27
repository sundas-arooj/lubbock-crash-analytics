"""Checks that the supplied Lubbock extract survives cleaning."""

from collections import Counter
from pathlib import Path

import pytest

from app.cleaning import load_export

CSV_PATH = Path(__file__).resolve().parents[1] / "district_crashes.csv"


@pytest.mark.skipif(not CSV_PATH.exists(), reason="CRIS extract is not in the workspace")
def test_lubbock_extract_matches_the_published_crash_count():
    export = load_export(CSV_PATH)
    assert export.district == "LUBBOCK"
    assert export.source_as_of == "2026-10-22"
    # The export preamble says 24,261 crashes and 67,906 persons.
    assert export.person_rows == 67906
    assert len(export.crashes) == 24261
    assert all(crash.crash_date for crash in export.crashes)
    severity = Counter(crash.severity for crash in export.crashes)
    assert severity == {"K": 624, "A": 1546, "B": 7224, "C": 14867}
    factors = Counter(factor for crash in export.crashes for factor in crash.factors)
    assert factors.most_common(5) == [
        ("FAILED TO CONTROL SPEED", 5559),
        ("FAILED TO YIELD RIGHT OF WAY - STOP SIGN", 2428),
        ("FAILED TO YIELD RIGHT OF WAY - TURNING LEFT", 2346),
        ("FAILED TO DRIVE IN SINGLE LANE", 2334),
        ("UNSAFE SPEED", 2034),
    ]
    assert "NONE" not in factors
    assert "NO DATA" not in factors
