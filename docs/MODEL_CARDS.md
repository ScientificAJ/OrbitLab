# OrbitLab Model Cards

Status: current for OrbitLab `v0.2.0`.

OrbitLab treats model artifacts as external scientific dependencies. A model is ready only when its registered files exist locally and pass checksum validation.

Global model-card rule: ML outputs are vetting evidence, not planet confirmation. A score may support, weaken, or contextualize a TCE, but final product wording must still distinguish reviewable TCEs, promoted `planet_candidates`, and externally confirmed planets.

## Nigraha TESS Ensemble

- Model ID: `nigraha-tess-global-nodropout-binary-ensemble`
- Mission: TESS
- Source: `ExoplanetML/Nigraha`
- Version: commit `c4365b41dd02b187c3210189ffe8e3ead584f4f5`
- Fetch script: `scripts/fetch_nigraha_weights.py`
- Format: Keras HDF5 ensemble directory
- Input contract: TESS candidate light-curve views prepared by the OrbitLab Nigraha adapter.
- Checksum policy: each HDF5 file is downloaded from the pinned commit and checked against a hard-coded SHA-256; the registered artifact directory is also hashed by OrbitLab.
- Limitations: ML scores are candidate-vetting signals, not confirmations. Missing or mismatched weights make the service unavailable.

## Kepler AstroNet-Family Checkpoint

- Model ID: `kepler-astronet-cnn-bilstm-attention`
- Mission: Kepler/K1
- Source: `bibinthomas123/Astronet`
- Version: commit `9809ce92306f11fbdc96f9830b522026710a3883`
- Fetch script: `scripts/fetch_kepler_astronet.py`
- Format: TensorFlow checkpoint directory
- Runtime note: the local launch path ensures a TensorFlow 1.x Docker image is present for the registered checkpoint path.
- Input contract: AstroNet-compatible global and local folded views plus candidate metadata produced by the OrbitLab adapter.
- Checksum policy: checkpoint files are rejected if they resolve to Git LFS pointers and are checked against hard-coded SHA-256 values before registration.
- Limitations: the adapter validates artifact readiness before inference. If the checkpoint, Docker runtime, or expected tensor contract is unavailable, OrbitLab reports that state.

## K2 ExoMAC-KKT RandomForest

- Model ID: `k2-exomac-kkt-randomforest`
- Mission: K2
- Source: `ZapatoProgramming/ExoMAC-KKT`
- Version: Hugging Face revision `5cda5310d5a163679c6915f9463a4d6afc312483`
- Fetch script: `scripts/fetch_k2_exomac_kkt.py`
- Format: sklearn joblib bundle with feature schema, labels, and metadata
- Input contract: 16 catalog-style features mapped from a detected K2 candidate, including period, depth, duration, SNR, stellar context when supplied, and derived log/duty-cycle features.
- Checksum policy: every bundle file is checked against a hard-coded SHA-256; feature columns, labels, and model metadata are validated before registration.
- Limitations: ExoMAC-KKT is a tabular candidate classifier, not a light-curve CNN. Its output should be interpreted as triage support.
- Replacement note: this is OrbitLab's registered K2 ML surface in place of the previously documented K2 AstroNet provenance-only entry.

## Public Readiness Surface

Use:

```bash
curl http://127.0.0.1:8000/api/v1/models
```

The response is the public truth for demo and contributor workflows. Ready means artifact files exist and checksums match. Unavailable means the service cannot honestly produce model-backed outputs.

## Release Provenance

Every public release should include the model-card truth in machine-checkable form through the Science Provenance Release Room:

- `model-artifact-checksums.json` records registered model paths, expected checksums, actual checksums, and readiness/mismatch detail.
- `calibration-source-checksums.json` tracks this model-card document, `docs/model_artifacts.md`, and key calibration/science source files.
- `orbitlab-release-report.md` summarizes ready and unavailable/mismatched model IDs for release reviewers.

Reviewers should compare `GET /api/v1/models` from the running app with the release-room artifact when debugging deployment drift. If the running app reports a model as ready but the release packet reported it unavailable, the deployment likely has newer local artifacts than the release build. If the release packet reported ready but the running app reports unavailable, inspect the deployed registry path, mounted artifact volume, and checksums.
