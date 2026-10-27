"""Turn the TxDOT CRIS export into one record per crash.

The file opens with a disclaimer and the query description. The table header
is the first row whose first column is "Crash ID". Each data row is a person
involved in a crash, and the crash attributes are repeated on every person
row. Counts in this project are crash counts, so later rows for a crash id
that was already seen are ignored.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Words TxDOT uses when a value was not reported. "NONE" is included because
# a contributing-factor rank should describe reported factors, not the
# code for "no factor listed".
SENTINELS = {
    "",
    "NO DATA",
    "N/A",
    "NA",
    "NONE",
    "NOT REPORTED",
    "NOT APPLICABLE",
    "UNKNOWN",
}

# Coordinates outside this window are not usable Texas locations. The gate
# drops "No Data", 0,0, and other broken geocodes without removing crashes
# from the counts.
TEXAS_LATITUDE = (25.0, 37.0)
TEXAS_LONGITUDE = (-107.0, -93.0)

SEVERITY_LABELS = {
    "K": "Fatal injury",
    "A": "Suspected serious injury",
    "B": "Suspected minor injury",
    "C": "Possible injury",
}
SEVERITY_ORDER = ("K", "A", "B", "C")

REQUIRED_COLUMNS = (
    "Crash ID",
    "Crash Severity",
    "Contributing Factors",
    "County",
    "Crash Date",
    "Crash Year",
    "Crash Time",
    "Latitude",
    "Longitude",
    "Road Class",
    "Crash Death Count",
)

_AS_OF = re.compile(r"as of\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
_DISTRICT = re.compile(
    r"TxDOT District Is Equal To\s+([A-Za-z ]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Crash:
    crash_id: str
    severity: str | None
    crash_date: str | None
    crash_year: int | None
    crash_month: int | None
    crash_hour: int | None
    county: str | None
    road_class: str | None
    latitude: float | None
    longitude: float | None
    death_count: int
    factors: tuple[str, ...]


@dataclass(frozen=True)
class Export:
    crashes: list[Crash]
    source_as_of: str | None
    district: str | None
    person_rows: int


def load_export(path: Path | str) -> Export:
    """Read a CRIS export and return one Crash per crash id."""
    path = Path(path)
    crashes: dict[str, Crash] = {}
    person_rows = 0
    source_as_of = None
    district = None

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = None
        for row in reader:
            if row and row[0].lstrip("\ufeff").strip() == "Crash ID":
                header = [name.lstrip("\ufeff").strip() for name in row]
                break
            text = " ".join(cell.strip() for cell in row if cell and cell.strip())
            if not text:
                continue
            if source_as_of is None:
                matched = _AS_OF.search(text)
                if matched:
                    source_as_of = datetime.strptime(
                        matched.group(1), "%m/%d/%Y"
                    ).date().isoformat()
            if district is None:
                matched = _DISTRICT.search(text)
                if matched:
                    district = matched.group(1).strip(" .,").upper()
        if header is None:
            raise ValueError(f"No crash table found in {path.name}.")
        missing = [name for name in REQUIRED_COLUMNS if name not in header]
        if missing:
            raise ValueError(f"Export is missing columns: {', '.join(missing)}")

        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            person_rows += 1
            padded = row + [""] * (len(header) - len(row))
            record = dict(zip(header, padded))
            crash_id = record["Crash ID"].strip()
            if not crash_id or crash_id in crashes:
                continue
            crashes[crash_id] = _build_crash(crash_id, record)

    return Export(
        crashes=list(crashes.values()),
        source_as_of=source_as_of,
        district=district,
        person_rows=person_rows,
    )


def parse_severity(value: str | None) -> str | None:
    """Return K, A, B, or C from a CRIS severity label."""
    if value is None:
        return None
    text = " ".join(value.split()).upper()
    if not text or text in SENTINELS:
        return None
    if text in SEVERITY_LABELS:
        return text
    letter = text[0]
    if letter in SEVERITY_LABELS and (len(text) == 1 or text[1] in {" ", "-", ":"}):
        return letter
    return None


def parse_factors(value: str | None) -> tuple[str, ...]:
    """Split the combined contributing-factor field into unique labels.

    CRIS joins several factors with semicolons. The separate factor columns
    carry the same text plus a numeric code, and they are often "No Data"
    even when this combined field is filled, so the combined field is the
    one this project ranks.
    """
    if value is None:
        return ()
    found: list[str] = []
    for part in value.split(";"):
        label = " ".join(part.split()).upper()
        if not label or label in SENTINELS or label in found:
            continue
        found.append(label)
    return tuple(found)


def parse_coordinates(
    latitude: str | None, longitude: str | None
) -> tuple[float | None, float | None]:
    try:
        lat = float(str(latitude).strip())
        lon = float(str(longitude).strip())
    except (TypeError, ValueError):
        return None, None
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None, None
    lat_min, lat_max = TEXAS_LATITUDE
    lon_min, lon_max = TEXAS_LONGITUDE
    if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
        return None, None
    return lat, lon


def parse_hour(value: str | None) -> int | None:
    """Read an hour from a CRIS time such as 0827 or 13:20."""
    if value is None:
        return None
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 3:
        return None
    digits = digits.zfill(4)
    hour = int(digits[:2])
    minute = int(digits[2:4])
    if hour > 23 or minute > 59:
        return None
    return hour


def _build_crash(crash_id: str, record: dict[str, str]) -> Crash:
    parsed_date = _parse_date(record.get("Crash Date"))
    if parsed_date is None:
        crash_date = None
        crash_month = None
        crash_year = _parse_year(record.get("Crash Year"))
    else:
        crash_date, crash_year, crash_month = parsed_date
    latitude, longitude = parse_coordinates(
        record.get("Latitude"), record.get("Longitude")
    )
    return Crash(
        crash_id=crash_id,
        severity=parse_severity(record.get("Crash Severity")),
        crash_date=crash_date,
        crash_year=crash_year,
        crash_month=crash_month,
        crash_hour=parse_hour(record.get("Crash Time")),
        county=_clean_token(record.get("County")),
        road_class=_clean_token(record.get("Road Class")),
        latitude=latitude,
        longitude=longitude,
        death_count=_parse_count(record.get("Crash Death Count")),
        factors=parse_factors(record.get("Contributing Factors")),
    )


def _parse_date(value: str | None) -> tuple[str, int, int] | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() in SENTINELS:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.date().isoformat(), parsed.year, parsed.month


def _parse_year(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() in SENTINELS:
        return None
    try:
        year = int(text)
    except ValueError:
        return None
    if 1900 <= year <= 2100:
        return year
    return None


def _parse_count(value: str | None) -> int:
    if value is None:
        return 0
    text = value.strip()
    if not text or text.upper() in SENTINELS:
        return 0
    try:
        number = int(float(text))
    except ValueError:
        return 0
    return number if number > 0 else 0


def _clean_token(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split()).upper()
    if not text or text in SENTINELS:
        return None
    return text
