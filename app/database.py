"""SQLite storage for the crash-level table.

The API reads this file. Rebuilding it is a separate step so a request never
parses the original extract.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.cleaning import Export

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def database_path() -> Path:
    override = os.environ.get("CRASH_DB_PATH")
    if override:
        return Path(override)
    return PACKAGE_ROOT / "data" / "processed" / "crashes.db"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or database_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Processed database not found at {path}. "
            "Run: python scripts/process_data.py"
        )
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def write_database(export: Export, db_path: Path | None = None) -> Path:
    """Replace the processed database with this export."""
    target = db_path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".db.tmp")
    if temporary.exists():
        temporary.unlink()

    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE crashes (
                crash_id TEXT PRIMARY KEY,
                severity TEXT,
                crash_date TEXT,
                crash_year INTEGER,
                crash_month INTEGER,
                crash_hour INTEGER,
                county TEXT,
                road_class TEXT,
                latitude REAL,
                longitude REAL,
                death_count INTEGER NOT NULL
            );

            CREATE TABLE crash_factors (
                crash_id TEXT NOT NULL REFERENCES crashes(crash_id),
                factor TEXT NOT NULL,
                PRIMARY KEY (crash_id, factor)
            );

            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE INDEX idx_crashes_county ON crashes(county);
            CREATE INDEX idx_crashes_year ON crashes(crash_year);
            CREATE INDEX idx_crashes_severity ON crashes(severity);
            CREATE INDEX idx_crashes_road ON crashes(road_class);
            CREATE INDEX idx_factors_factor ON crash_factors(factor);
            """
        )
        connection.executemany(
            """
            INSERT INTO crashes (
                crash_id, severity, crash_date, crash_year, crash_month,
                crash_hour, county, road_class, latitude, longitude, death_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    crash.crash_id,
                    crash.severity,
                    crash.crash_date,
                    crash.crash_year,
                    crash.crash_month,
                    crash.crash_hour,
                    crash.county,
                    crash.road_class,
                    crash.latitude,
                    crash.longitude,
                    crash.death_count,
                )
                for crash in export.crashes
            ),
        )
        connection.executemany(
            "INSERT INTO crash_factors (crash_id, factor) VALUES (?, ?)",
            (
                (crash.crash_id, factor)
                for crash in export.crashes
                for factor in crash.factors
            ),
        )
        unmapped = sum(1 for crash in export.crashes if crash.latitude is None)
        without_factors = sum(1 for crash in export.crashes if not crash.factors)
        metadata = {
            "source_as_of": export.source_as_of or "",
            "district": export.district or "",
            "person_rows": str(export.person_rows),
            "crash_count": str(len(export.crashes)),
            "unmapped_crashes": str(unmapped),
            "crashes_without_factors": str(without_factors),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            metadata.items(),
        )
        connection.commit()
    finally:
        connection.close()

    os.replace(temporary, target)
    return target


def read_metadata(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT key, value FROM metadata").fetchall()
    return {
        row["key"]: row["value"]
        for row in rows
        if row["value"] not in (None, "")
    }
