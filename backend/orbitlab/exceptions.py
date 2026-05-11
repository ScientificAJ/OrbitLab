class OrbitLabError(RuntimeError):
    """Base exception for domain-level failures."""


class RealDataRequiredError(OrbitLabError):
    """Raised when an operation would require fabricated science data."""


class ModelArtifactError(OrbitLabError):
    """Raised when a pretrained model artifact is missing or invalid."""
