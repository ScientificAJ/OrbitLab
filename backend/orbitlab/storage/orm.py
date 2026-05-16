from __future__ import annotations

import typing
from datetime import datetime, timezone

try:
    from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Float, JSON, Index
    from sqlalchemy.orm import Mapped, mapped_column, relationship
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install orbitlab[api] to use SQLAlchemy storage models") from exc

from orbitlab.storage.database import Base


class AnalysisJobRecord(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        Index("ix_analysis_jobs_target_mission", "target_id", "mission"),
        Index("ix_analysis_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(128), index=True)
    product_uri: Mapped[str] = mapped_column(Text)
    mission: Mapped[str] = mapped_column(String(16), index=True)
    aperture_mask_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_mask_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_candidates: Mapped[int] = mapped_column(Integer, default=4)
    stellar_radius_solar: Mapped[float | None] = mapped_column(Float, nullable=True)
    stellar_mass_solar: Mapped[float | None] = mapped_column(Float, nullable=True)
    stellar_teff: Mapped[float | None] = mapped_column(Float, nullable=True)
    stellar_logg: Mapped[float | None] = mapped_column(Float, nullable=True)
    stellar_luminosity_solar: Mapped[float | None] = mapped_column(Float, nullable=True)
    stellar_density_solar: Mapped[float | None] = mapped_column(Float, nullable=True)
    stellar_rotation_period: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    result: Mapped["AnalysisResultRecord | None"] = relationship(back_populates="job")


class AnalysisResultRecord(Base):
    __tablename__ = "analysis_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("analysis_jobs.id"), unique=True)
    payload_json: Mapped[typing.Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    job: Mapped[AnalysisJobRecord] = relationship(back_populates="result")


class SavedSessionRecord(Base):
    __tablename__ = "saved_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    payload_json: Mapped[typing.Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ArtifactMaskRecord(Base):
    __tablename__ = "artifact_masks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(128), index=True)
    indices_json: Mapped[typing.Any] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ApertureMaskRecord(Base):
    __tablename__ = "aperture_masks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(128), index=True)
    product_uri: Mapped[str] = mapped_column(Text)
    mask_json: Mapped[typing.Any] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
