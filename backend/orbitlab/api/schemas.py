from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"


class SearchResult(BaseModel):
    target_id: str
    ra: float | None = None
    dec: float | None = None
    catalog: str
    match_type: str = Field(default="catalog", pattern="^(catalog|alias)$")
    matched_query: str | None = None


class Product(BaseModel):
    product_id: str
    mission: str
    description: str
    size: int | None = None
    product_uri: str


class AnalysisJobCreate(BaseModel):
    target_id: str
    product_uri: str
    mission: str = Field(pattern="^(TESS|Kepler|K2)$")
    aperture_mask_id: str | None = None
    artifact_mask_id: str | None = None
    max_candidates: int = Field(default=4, ge=1, le=8)
    vetting_mode: Literal["paper", "deep", "fast"] = "paper"
    stellar_radius_solar: float | None = Field(default=None, gt=0)
    stellar_mass_solar: float | None = Field(default=None, gt=0)
    stellar_teff: float | None = Field(default=None, gt=0)
    stellar_logg: float | None = Field(default=None, gt=0)
    stellar_luminosity_solar: float | None = Field(default=None, gt=0)
    stellar_density_solar: float | None = Field(default=None, gt=0)
    stellar_rotation_period: float | None = Field(default=None, gt=0)


class BlsPreviewCreate(BaseModel):
    product_uri: str
    mission: str = Field(pattern="^(TESS|Kepler|K2)$")
    aperture_mask_id: str | None = None
    min_period: float = Field(default=0.5, gt=0)
    max_period: float = Field(default=30.0, gt=0)
    max_candidates: int = Field(default=4, ge=1, le=8)

    @model_validator(mode="after")
    def validate_period_range(self):
        if self.min_period >= self.max_period:
            raise ValueError("min_period must be less than max_period")
        return self


class AnalysisJob(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    result_id: str | None = None
    error: str | None = None


class CandidatePayload(BaseModel):
    candidate_id: str
    period: float
    epoch: float
    duration: float
    depth: float
    signal_to_noise: float
    raw_snr: float | None = None
    red_noise_beta: float | None = None
    effective_snr: float | None = None
    final_score: float | None = None
    evidence: dict[str, Any] | None = None
    evidence_scores: dict[str, Any] | None = None
    explanation: list[str] = Field(default_factory=list)
    physics: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    period_source: str | None = None
    signal_origin: str | None = None
    catalog_match: dict[str, Any] | None = None
    is_residual: bool | None = None
    display_priority: int | None = None
    secondary_context: dict[str, Any] | None = None
    ml: dict[str, Any] | None = None


class TcePayload(CandidatePayload):
    tce_id: str | None = None
    period_days: float | None = None
    epoch_days: float | None = None
    duration_days: float | None = None
    depth_fraction: float | None = None
    depth_ppm: float | None = None
    duration_hours: float | None = None
    disposition: Literal["planet_candidate", "borderline_tce", "rejected_signal"] | None = None
    action_label: Literal["none", "review_needed", "follow_up_needed"] | None = None
    disposition_score: float | None = None
    confidence_band: str | None = None
    flags: list[dict[str, Any]] = Field(default_factory=list)
    detection_metrics: dict[str, Any] | None = None
    aperture_stability: dict[str, Any] | None = None
    vetting: dict[str, Any] | None = None
    catalog_context: dict[str, Any] | None = None
    fpp: dict[str, Any] | None = None


class StellarContext(BaseModel):
    radius_solar: float | None = None
    mass_solar: float | None = None
    teff: float | None = None
    logg: float | None = None
    luminosity_solar: float | None = None
    density_solar: float | None = None
    rotation_period: float | None = None
    effective_radius_solar: float | None = None
    effective_mass_solar: float | None = None
    effective_teff: float | None = None
    physics_source: str | None = None


class AnalysisResult(BaseModel):
    result_id: str
    target_id: str
    mission: str
    candidates: list[CandidatePayload]
    schema_version: str | None = None
    pipeline_version: str | None = None
    science_config_hash: str | None = None
    vetting_mode: Literal["paper", "deep", "fast"] | None = None
    data_quality: dict[str, Any] | None = None
    tces: list[TcePayload] = Field(default_factory=list)
    planet_candidates: list[TcePayload] = Field(default_factory=list)
    validation_status: str | None = None
    engine_status: dict[str, Any] | None = None
    deep_mode_progress: dict[str, Any] | None = None
    search_profile: str | None = None
    active_science_config_keys: list[str] = Field(default_factory=list)
    inactive_science_config_keys: list[str] = Field(default_factory=list)
    missing_science_config_keys: list[str] = Field(default_factory=list)
    injection_recovery: dict[str, Any] | None = None
    periodogram: dict[str, list[float]]
    folded_curves: dict[str, dict[str, list[float]]]
    light_curve: dict[str, list[float]]
    bls_light_curve: dict[str, list[float]] | None = None
    stellar_context: StellarContext | None = None
    preprocessing: dict[str, Any] | None = None


class MaskCreate(BaseModel):
    target_id: str
    indices: list[int] = Field(min_length=1)
    reason: str

    @model_validator(mode="after")
    def validate_indices(self):
        if any(index < 0 for index in self.indices):
            raise ValueError("artifact mask indices must be non-negative")
        self.indices = sorted(set(self.indices))
        return self


class ApertureMaskCreate(BaseModel):
    target_id: str
    product_uri: str
    mask: list[list[bool]]
    reason: str

    @model_validator(mode="after")
    def validate_mask(self):
        if not self.mask or not self.mask[0]:
            raise ValueError("aperture mask must be a non-empty 2D grid")
        width = len(self.mask[0])
        if any(len(row) != width for row in self.mask):
            raise ValueError("aperture mask rows must all have the same length")
        if not any(pixel for row in self.mask for pixel in row):
            raise ValueError("aperture mask must select at least one pixel")
        return self


class ArtifactMaskResponse(BaseModel):
    mask_id: str
    target_id: str
    indices: list[int]
    reason: str
    created_at: datetime | str


class ApertureMaskResponse(BaseModel):
    aperture_mask_id: str
    target_id: str
    product_uri: str
    mask: list[list[bool]]
    reason: str
    created_at: datetime | str


class ReportResponse(BaseModel):
    report_id: str
    generated_at: str
    format: str
    result: dict[str, Any]


class SavedSession(BaseModel):
    session_id: str
    name: str
    payload: dict[str, Any]
    created_at: datetime


class SavedSessionCreate(BaseModel):
    name: str
    payload: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    api: str
    database: str
    worker_mode: str
    redis_configured: bool
    frontend: str
    generated_at: str
