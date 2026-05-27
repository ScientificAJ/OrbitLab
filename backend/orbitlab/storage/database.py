from __future__ import annotations

from orbitlab.config import settings

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import DeclarativeBase, sessionmaker
except ImportError as exc:  # pragma: no cover - optional api install
    raise RuntimeError("Install orbitlab[api] to use SQLAlchemy storage") from exc


class Base(DeclarativeBase):
    __abstract__ = True


def _ensure_database_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    path = database_url.removeprefix("sqlite:///")
    if path in {":memory:", ""}:
        return
    from pathlib import Path

    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_database_parent(settings.database_url)
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from orbitlab.storage import orm  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_analysis_job_columns()


def _ensure_analysis_job_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "analysis_jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("analysis_jobs")}
    expected_columns = {
        "artifact_mask_id": "VARCHAR(64)",
        "max_candidates": "INTEGER DEFAULT 4",
        "vetting_mode": "VARCHAR(16) DEFAULT 'paper'",
        "stellar_radius_solar": "FLOAT",
        "stellar_mass_solar": "FLOAT",
        "stellar_teff": "FLOAT",
        "stellar_logg": "FLOAT",
        "stellar_luminosity_solar": "FLOAT",
        "stellar_density_solar": "FLOAT",
        "stellar_rotation_period": "FLOAT",
    }

    with engine.begin() as conn:
        for column_name, ddl in expected_columns.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE analysis_jobs ADD COLUMN {column_name} {ddl}"))
