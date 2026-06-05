from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

from orbitlab.config import Settings, settings
from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.artifact_registry import get_registered_artifact
from orbitlab.ml.checksum import sha256_path
from orbitlab.ml.nigraha_adapter import NIGRAHA_MODEL_ID, NIGRAHA_SCHEMA_VERSION, NigrahaTensors


@dataclass(frozen=True)
class NigrahaModelInfo:
    model_id: str
    version: str
    source: str
    checksum: str
    schema_version: str
    status: str


@dataclass(frozen=True)
class NigrahaVerdict:
    probability: float
    threshold: float
    label: str
    model_version: str
    model_source: str
    input_tensor_checksum: str
    preprocessing_compatible: bool
    citation: str
    model_family: str
    imputed_features: tuple[str, ...]
    mean_logit: float | None = None
    saturated: bool = False
    score_confidence: str = "nominal"
    score_caveat: str | None = None
    standardized: bool = False
    standardized_features: tuple[str, ...] = ()


# The released Nigraha CNN expects its stellar scalar features (Teff, R*, logg,
# mass, luminosity, density) to be standardized per the training-set median/std
# before the dense head (Rao et al. 2021, MNRAS 502, 2845, sec. 3). Those
# constants are recovered from the committed upstream training catalog by
# scripts/recover_nigraha_norm_stats.py and applied in build_nigraha_tensors, so
# the normal path now feeds standardized scalars and the logit discriminates
# (score_confidence="nominal", preprocessing_compatible=True).
#
# The saturation gate below is retained as a SAFETY NET, not the primary state:
# if the norm-stats artifact is absent (fresh checkout before the recovery script
# has run) raw physical scalars enter the dense head unscaled, the logit is driven
# far past the sigmoid floor, and the probability saturates to a constant that
# carries no discrimination. In that fallback regime we detect the saturated
# logit (|logit| >= 50) and gate the score's confidence honestly rather than
# trusting a degenerate value. We never fabricate normalization.
_NIGRAHA_SATURATION_LOGIT = 50.0


_GLOBAL_NIGRAHA_CACHE: dict[str, tuple[NigrahaModelInfo, list[NigrahaNumpyModel]]] = {}


class NigrahaService:
    def __init__(self, config: Settings = settings, model_id: str = NIGRAHA_MODEL_ID):
        self.config = config
        self.model_id = model_id
        self.artifact = get_registered_artifact(model_id, config.model_registry_path)
        self.model_path = Path(self.artifact.path)

    def validate_artifact(self) -> NigrahaModelInfo:
        if not self.model_path.exists():
            raise ModelArtifactError(f"Nigraha artifact path does not exist: {self.model_path}")
        if not self.model_path.is_dir():
            raise ModelArtifactError("Nigraha ensemble artifact must be a directory")
        files = sorted(self.model_path.glob("models_*.hdf5"))
        if len(files) != 10:
            raise ModelArtifactError(f"Nigraha ensemble requires 10 .hdf5 files, found {len(files)}")
        actual = sha256_path(self.model_path)
        if actual.lower() != self.artifact.sha256.lower():
            raise ModelArtifactError("Nigraha ensemble checksum mismatch")
        return NigrahaModelInfo(
            model_id=self.model_id,
            version=self.artifact.version,
            source=self.artifact.source,
            checksum=actual,
            schema_version=NIGRAHA_SCHEMA_VERSION,
            status="ready",
        )

    def load(self) -> NigrahaModelInfo:
        global _GLOBAL_NIGRAHA_CACHE
        cache_key = f"{self.model_id}:{self.artifact.sha256}:{self.model_path}"
        if cache_key in _GLOBAL_NIGRAHA_CACHE:
            return _GLOBAL_NIGRAHA_CACHE[cache_key][0]

        info = self.validate_artifact()
        models = [NigrahaNumpyModel(path) for path in sorted(self.model_path.glob("models_*.hdf5"))]
        _GLOBAL_NIGRAHA_CACHE[cache_key] = (info, models)
        return info

    def predict(self, tensors: NigrahaTensors, *, threshold: float = 0.5) -> NigrahaVerdict:
        global _GLOBAL_NIGRAHA_CACHE
        if tensors.schema_version != NIGRAHA_SCHEMA_VERSION:
            raise ModelArtifactError("Nigraha tensor schema is incompatible")

        cache_key = f"{self.model_id}:{self.artifact.sha256}:{self.model_path}"
        if cache_key not in _GLOBAL_NIGRAHA_CACHE:
            self.load()

        info, models = _GLOBAL_NIGRAHA_CACHE[cache_key]
        inputs = tensors.as_inputs()
        results = [model.predict_with_logit(inputs) for model in models]
        scores = [score for score, _ in results]
        logits = [logit for _, logit in results]
        probability = min(max(float(np.mean(scores)), 0.0), 1.0)
        mean_logit = float(np.mean(logits))

        # Honest gating (safety net): when the ensemble logits are pushed past the
        # sigmoid's numerically saturated region, the probability carries no real
        # discrimination (it floors/ceils for essentially any candidate). On the
        # normal path the upstream-recovered scalar standardization keeps the logit
        # in the discriminating range; saturation here means the norm-stats artifact
        # was unavailable so raw scalars entered the dense head. Either way it is not
        # a real planet judgement, so we flag it rather than trusting it.
        standardized = getattr(tensors, "standardized", False)
        saturated = bool(np.all(np.abs(np.asarray(logits)) >= _NIGRAHA_SATURATION_LOGIT))
        if saturated:
            score_confidence = "degenerate_saturated"
            standardization_note = (
                "the upstream scalar standardization constants were unavailable, so raw "
                "physical scalars entered the dense head"
                if not standardized
                else "the standardized scalars still drove the logit into saturation"
            )
            score_caveat = (
                f"Nigraha ensemble logit is saturated ({mean_logit:.0f}); the released CNN expects "
                "standardized scalar features (Rao et al. 2021, MNRAS 502, 2845) and "
                f"{standardization_note}, so this probability does not discriminate between "
                "candidates and must not be trusted as ML evidence."
            )
        else:
            score_confidence = "nominal"
            score_caveat = None

        return NigrahaVerdict(
            probability=probability,
            threshold=threshold,
            label="planet-candidate" if probability >= threshold else "not-transit-like",
            model_version=info.version,
            model_source=info.source,
            input_tensor_checksum=tensors.checksum,
            preprocessing_compatible=not saturated,
            citation="Rao et al. 2021, MNRAS 502, 2845; ExoplanetML/Nigraha released TESS CNN weights.",
            model_family="Nigraha TESS CNN ensemble",
            imputed_features=tensors.imputed_features,
            mean_logit=mean_logit,
            saturated=saturated,
            score_confidence=score_confidence,
            score_caveat=score_caveat,
            standardized=standardized,
            standardized_features=getattr(tensors, "standardized_features", ()),
        )


class NigrahaNumpyModel:
    def __init__(self, path: Path):
        self.path = path
        self.weights = self._load_weights(path)

    @staticmethod
    def _load_weights(path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        weights: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        with h5py.File(path, "r") as h5:
            root = h5["model_weights"]
            for layer_name in root.keys():
                layer = root[layer_name]
                datasets: dict[str, np.ndarray] = {}

                def collect_dataset(name: str, obj, *, target: dict[str, np.ndarray] = datasets) -> None:
                    if hasattr(obj, "shape"):
                        target[name.rsplit("/", 1)[-1].replace(":0", "")] = obj[()]

                layer.visititems(collect_dataset)
                if "kernel" in datasets and "bias" in datasets:
                    weights[layer_name] = (
                        np.asarray(datasets["kernel"], dtype=np.float32),
                        np.asarray(datasets["bias"], dtype=np.float32),
                    )
        return weights

    @staticmethod
    def _relu(x: np.ndarray) -> np.ndarray:
        return np.maximum(x, 0.0)

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(x, -60.0, 60.0)))

    @staticmethod
    def _conv1d_same(x: np.ndarray, kernel: np.ndarray, bias: np.ndarray) -> np.ndarray:
        batch, length, channels = x.shape
        width, in_channels, out_channels = kernel.shape
        if channels != in_channels:
            raise ModelArtifactError(f"channel mismatch for convolution: {channels} != {in_channels}")
        pad_left = (width - 1) // 2
        pad_right = width - 1 - pad_left
        padded = np.pad(x, ((0, 0), (pad_left, pad_right), (0, 0)), mode="constant")
        windows = np.lib.stride_tricks.sliding_window_view(padded, window_shape=width, axis=1)
        # windows shape: batch, length, channels, width
        windows = np.moveaxis(windows, -1, 2)
        # batch, length, width, channels
        return np.tensordot(windows, kernel, axes=([2, 3], [0, 1])) + bias

    @staticmethod
    def _max_pool1d_valid(x: np.ndarray, pool_size: int, stride: int) -> np.ndarray:
        batch, length, channels = x.shape
        windows = np.lib.stride_tricks.sliding_window_view(x, window_shape=pool_size, axis=1)
        # batch, out_length, channels, pool_size
        windows = windows[:, ::stride, :, :]
        return np.max(windows, axis=-1)

    def _conv_layer(self, x: np.ndarray, layer_name: str) -> np.ndarray:
        kernel, bias = self.weights[layer_name]
        return self._relu(self._conv1d_same(x, kernel, bias))

    def _global_path(self, x: np.ndarray) -> np.ndarray:
        layer_pairs = (
            ("conv1d", "conv1d_1"),
            ("conv1d_2", "conv1d_3"),
            ("conv1d_4", "conv1d_5"),
            ("conv1d_6", "conv1d_7"),
            ("conv1d_8", "conv1d_9"),
        )
        for first, second in layer_pairs:
            x = self._conv_layer(x, first)
            x = self._conv_layer(x, second)
            x = self._max_pool1d_valid(x, 5, 2)
        return x.reshape((x.shape[0], -1))

    def _local_path(self, x: np.ndarray, offset: int) -> np.ndarray:
        layer_pairs = (
            (f"conv1d_{offset}", f"conv1d_{offset + 1}"),
            (f"conv1d_{offset + 2}", f"conv1d_{offset + 3}"),
        )
        for first, second in layer_pairs:
            x = self._conv_layer(x, first)
            x = self._conv_layer(x, second)
            x = self._max_pool1d_valid(x, 3, 2)
        return x.reshape((x.shape[0], -1))

    def _dense(self, x: np.ndarray, layer_name: str, *, activation: str) -> np.ndarray:
        kernel, bias = self.weights[layer_name]
        y = x @ kernel + bias
        if activation == "relu":
            return self._relu(y)
        if activation == "sigmoid":
            return self._sigmoid(y)
        return y

    def predict_with_logit(self, inputs: dict[str, np.ndarray]) -> tuple[float, float]:
        global_path = self._global_path(np.asarray(inputs["global_view"], dtype=np.float32))
        local_path = self._local_path(np.asarray(inputs["local_view"], dtype=np.float32), 10)
        odd_even_path = self._local_path(np.asarray(inputs["odd_even_view"], dtype=np.float32), 14)
        scalars = [
            np.asarray(inputs[name], dtype=np.float32).reshape(1, 1)
            for name in (
                "Depth",
                "Duration",
                "Teff",
                "Radius",
                "logg",
                "Mass",
                "lum",
                "rho",
                "rp_rs",
                "DepthEven",
                "DepthOdd",
            )
        ]
        x = np.concatenate([global_path, local_path, odd_even_path, *scalars], axis=1)
        x = self._dense(x, "dense", activation="relu")
        x = self._dense(x, "dense_1", activation="relu")
        x = self._dense(x, "dense_2", activation="relu")
        x = self._dense(x, "dense_3", activation="relu")
        kernel, bias = self.weights["prediction"]
        logit = float((x @ kernel + bias).reshape(-1)[0])
        probability = float(self._sigmoid(np.asarray([logit], dtype=np.float32)).reshape(-1)[0])
        return probability, logit

    def predict(self, inputs: dict[str, np.ndarray]) -> float:
        probability, _logit = self.predict_with_logit(inputs)
        return probability
