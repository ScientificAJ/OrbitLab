from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./.orbitlab/orbitlab.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    astronet_model_path: Path | None = (
        Path(os.environ["ORBITLAB_ASTRONET_MODEL_PATH"])
        if os.getenv("ORBITLAB_ASTRONET_MODEL_PATH")
        else None
    )
    astronet_model_id: str = os.getenv("ORBITLAB_ASTRONET_MODEL_ID", "astronet-family-pretrained")
    astronet_model_sha256: str | None = os.getenv("ORBITLAB_ASTRONET_MODEL_SHA256")
    astronet_model_source: str = os.getenv(
        "ORBITLAB_ASTRONET_MODEL_SOURCE",
        "Google Research exoplanet-ml / AstroNet-compatible pretrained artifact",
    )
    astronet_model_version: str = os.getenv("ORBITLAB_ASTRONET_MODEL_VERSION", "external")
    run_jobs_inline: bool = os.getenv("ORBITLAB_RUN_JOBS_INLINE", "1").strip().lower() in {"1", "true", "yes"}
    mast_cache_dir: Path = Path(os.getenv("ORBITLAB_MAST_CACHE_DIR", ".orbitlab/mast")).resolve()
    model_registry_path: Path = Path(os.getenv("ORBITLAB_MODEL_REGISTRY", ".orbitlab/models.json")).resolve()
    cors_origins: tuple[str, ...] = _csv_env(
        "ORBITLAB_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    )
    api_prefix: str = "/api/v1"


settings = Settings()
