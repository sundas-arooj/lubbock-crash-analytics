"""Queries behind the API.

Every count is a count of crashes. A crash with two contributing factors
adds one to each factor, so factor shares can add up to more than 100%.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.cleaning import SEVERITY_LABELS, SEVERITY_ORDER

GRAINS = ("month", "year", "hour")


class FilterError(ValueError):
    """The caller asked for a filter this API does not understand."""


@dataclass(frozen=True)
class Filters:
    county: str | None = None
    year: int | None = None
    severity: str | None = None
    road_class: str | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "county": self.county,
            "year": self.year,
            "severity": self.severity,
            "road_class": self.road_class,
        }


def parse_filters(
    county: str | None = None,
    year: int | None = None,
    severity: str | None = None,
    road_class: str | None = None,
) -> Filters:
    cleaned_severity = _blank(severity)
    if cleaned_severity is not None:
        cleaned_severity = cleaned_severity.upper()
        if cleaned_severity not in SEVERITY_LABELS:
            raise FilterError("severity must be one of K, A, B, C.")
    cleaned_year = year
    if cleaned_year is not None and not 1900 <= cleaned_year <= 2100:
        raise FilterError("year is outside the supported range.")
    return Filters(
        county=_token(_blank(county)),
        year=cleaned_year,
        severity=cleaned_severity,
        road_class=_token(_blank(road_class)),
    )


def crash_total(connection: sqlite3.Connection, filters: Filters) -> tuple[int, int]:
    """Return the crash count and the summed death count."""
    where, params = _where(filters)
    row = connection.execute(
        f"SELECT COUNT(*), COALESCE(SUM(death_count), 0) FROM crashes {where}",
        params,
    ).fetchone()
    return int(row[0]), int(row[1])


def severity_counts(connection: sqlite3.Connection, filters: Filters) -> list[dict]:
    where, params = _where(filters)
    rows = connection.execute(
        f"""
        SELECT severity, COUNT(*) AS n
        FROM crashes
        {where}
        GROUP BY severity
        """,
        params,
    ).fetchall()
    found = {row["severity"]: int(row["n"]) for row in rows}
    total = sum(found.values())
    return [
        {
            "severity": code,
            "label": SEVERITY_LABELS[code],
            "count": found.get(code, 0),
            "share": _share(found.get(code, 0), total),
        }
        for code in SEVERITY_ORDER
    ]


def top_factors(
    connection: sqlite3.Connection, filters: Filters, limit: int = 5
) -> list[dict]:
    where, params = _where(filters, alias="c")
    total, _deaths = crash_total(connection, filters)
    rows = connection.execute(
        f"""
        SELECT f.factor AS factor, COUNT(*) AS n
        FROM crash_factors AS f
        JOIN crashes AS c ON c.crash_id = f.crash_id
        {where}
        GROUP BY f.factor
        ORDER BY n DESC, f.factor ASC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return [
        {
            "rank": index,
            "factor": row["factor"],
            "count": int(row["n"]),
            "share": _share(int(row["n"]), total),
        }
        for index, row in enumerate(rows, start=1)
    ]


def trends(
    connection: sqlite3.Connection, filters: Filters, grain: str = "month"
) -> list[dict]:
    if grain not in GRAINS:
        raise FilterError("grain must be one of month, year, hour.")
    where, params = _where(filters)
    if grain == "hour":
        rows = connection.execute(
            f"""
            SELECT crash_hour AS hour, COUNT(*) AS n
            FROM crashes
            {_and(where, "crash_hour IS NOT NULL")}
            GROUP BY crash_hour
            """,
            params,
        ).fetchall()
        found = {int(row["hour"]): int(row["n"]) for row in rows}
        return [
            {"period": f"{hour:02d}:00", "hour": hour, "count": found.get(hour, 0)}
            for hour in range(24)
        ]
    if grain == "year":
        rows = connection.execute(
            f"""
            SELECT crash_year AS year, COUNT(*) AS n
            FROM crashes
            {_and(where, "crash_year IS NOT NULL")}
            GROUP BY crash_year
            ORDER BY crash_year
            """,
            params,
        ).fetchall()
        found = {int(row["year"]): int(row["n"]) for row in rows}
        return _fill_years(found)
    rows = connection.execute(
        f"""
        SELECT crash_year AS year, crash_month AS month, COUNT(*) AS n
        FROM crashes
        {_and(where, "crash_year IS NOT NULL AND crash_month IS NOT NULL")}
        GROUP BY crash_year, crash_month
        ORDER BY crash_year, crash_month
        """,
        params,
    ).fetchall()
    found = {(int(row["year"]), int(row["month"])): int(row["n"]) for row in rows}
    return _fill_months(found)


def locations(
    connection: sqlite3.Connection, filters: Filters, limit: int
) -> dict:
    where, params = _where(filters)
    total, _deaths = crash_total(connection, filters)
    rows = connection.execute(
        f"""
        SELECT crash_id, latitude, longitude, severity, county, crash_date
        FROM crashes
        {_and(where, "latitude IS NOT NULL AND longitude IS NOT NULL")}
        ORDER BY crash_date, crash_id
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return {
        "crash_count": total,
        "returned": len(rows),
        "locations": [
            {
                "crash_id": row["crash_id"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "severity": row["severity"],
                "county": row["county"],
                "crash_date": row["crash_date"],
            }
            for row in rows
        ],
    }


def filter_choices(connection: sqlite3.Connection) -> dict:
    counties = connection.execute(
        """
        SELECT DISTINCT county FROM crashes
        WHERE county IS NOT NULL
        ORDER BY county
        """
    ).fetchall()
    years = connection.execute(
        """
        SELECT DISTINCT crash_year AS year FROM crashes
        WHERE crash_year IS NOT NULL
        ORDER BY crash_year
        """
    ).fetchall()
    roads = connection.execute(
        """
        SELECT DISTINCT road_class FROM crashes
        WHERE road_class IS NOT NULL
        ORDER BY road_class
        """
    ).fetchall()
    return {
        "counties": [row["county"] for row in counties],
        "years": [int(row["year"]) for row in years],
        "road_classes": [row["road_class"] for row in roads],
        "severities": [
            {"code": code, "label": SEVERITY_LABELS[code]} for code in SEVERITY_ORDER
        ],
    }


def _where(filters: Filters, alias: str | None = None) -> tuple[str, list]:
    column = (lambda name: f"{alias}.{name}") if alias else (lambda name: name)
    clauses: list[str] = []
    params: list = []
    if filters.county is not None:
        clauses.append(f"{column('county')} = ?")
        params.append(filters.county)
    if filters.year is not None:
        clauses.append(f"{column('crash_year')} = ?")
        params.append(filters.year)
    if filters.severity is not None:
        clauses.append(f"{column('severity')} = ?")
        params.append(filters.severity)
    if filters.road_class is not None:
        clauses.append(f"{column('road_class')} = ?")
        params.append(filters.road_class)
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _and(where: str, extra: str) -> str:
    if where:
        return f"{where} AND {extra}"
    return f"WHERE {extra}"


def _fill_months(counts: dict[tuple[int, int], int]) -> list[dict]:
    if not counts:
        return []
    year, month = min(counts)
    end = max(counts)
    rows = []
    while (year, month) <= end:
        rows.append(
            {
                "period": f"{year}-{month:02d}",
                "year": year,
                "month": month,
                "count": counts.get((year, month), 0),
            }
        )
        month += 1
        if month == 13:
            month = 1
            year += 1
    return rows


def _fill_years(counts: dict[int, int]) -> list[dict]:
    if not counts:
        return []
    return [
        {"period": str(year), "year": year, "count": counts.get(year, 0)}
        for year in range(min(counts), max(counts) + 1)
    ]


def _share(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _token(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).upper()
