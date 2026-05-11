# Pretrained ML Artifacts

OrbitLab does not bundle fabricated ML checkpoints. TESS uses the registered Nigraha ensemble. Kepler uses the registered pinned AstroNet TensorFlow checkpoint through a Docker TensorFlow 1.x runtime, or an explicitly registered compatible `.npz`/`.onnx` artifact. K2 uses the registered ExoMAC-KKT sklearn bundle, a no-training classifier trained on NASA Kepler, K2, and TESS candidate catalogs. Every artifact is validated with SHA-256 before inference:

```bash
export ORBITLAB_ASTRONET_MODEL_PATH=/models/astronet/kepler.npz
export ORBITLAB_ASTRONET_MODEL_SHA256=$(sha256sum /models/astronet/kepler.npz | awk '{print $1}')
export ORBITLAB_ASTRONET_MODEL_SOURCE="External AstroNet-compatible Kepler artifact"
export ORBITLAB_ASTRONET_MODEL_VERSION="mission-specific-version"
```

Model policy:

- TESS: ExoplanetML/Nigraha registered ensemble.
- Kepler: `kepler-astronet-cnn-bilstm-attention`, fetched from the pinned `bibinthomas123/Astronet` TensorFlow checkpoint.
- K2: `k2-exomac-kkt-randomforest`, fetched from `ZapatoProgramming/ExoMAC-KKT` at commit `5cda5310d5a163679c6915f9463a4d6afc312483`.

Fetch and register K2:

```bash
scripts/fetch_k2_exomac_kkt.py
```

K2 inference is tabular candidate-vetting ML, not an AstroNet-K2 light-curve CNN. OrbitLab maps each detected K2 candidate into the model's 16 catalog features, including period, duration in hours, depth, SNR, stellar context when supplied, and derived log/duty-cycle features.

The API refuses to report model readiness when the artifact is absent, empty, or checksum-mismatched.
