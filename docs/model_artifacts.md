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

K2 inference is tabular candidate-vetting ML through the registered ExoMAC-KKT replacement model. OrbitLab maps each detected K2 candidate into the model's 16 catalog features, including period, duration in hours, depth, SNR, stellar context when supplied, and derived log/duty-cycle features.

## Input Normalization

- TESS/Nigraha: folded global, local, and odd/even views are median-centered and scaled by transit depth or robust scatter. Missing scalar stellar context is imputed with solar-like defaults and recorded in the adapter payload.
- Kepler/AstroNet: global and local folded views use AstroNet-style median-centering and minimum-flux scaling; the local view spans four transit durations on either side of mid-transit. Metadata carries period, epoch, duration, depth, SNR, and optional stellar radius/mass.
- K2/ExoMAC-KKT: catalog features preserve ExoMAC units: period in days, duration in hours, fractional depth, SNR, optional stellar context, and derived log/duty-cycle features. Missing optional values are encoded as NaN for the sklearn pipeline.

The API refuses to report model readiness when the artifact is absent, empty, or checksum-mismatched.

## Paper-Grade Science Engines

The default accuracy path also requires the installed science packages from `pyproject.toml`: `transitleastsquares`, `wotan`, `triceratops`, `astroquery`, and their numeric dependencies. Official DAVE model-shift vetting is not a pip package, so OrbitLab expects the compiled DAVE binary at `.orbitlab/external/DAVE/vetting/modshift` or the path in `ORBITLAB_DAVE_MODSHIFT`.

Build the DAVE executable:

```bash
scripts/build_dave_modshift.sh
```

Paper-grade TESS promotion uses TLS, Wotan biweight detrending, DAVE ModShift/RoboVet, DAVE SWEET, TIC/Gaia contamination context, TRICERATOPS FPP/NFPP thresholds, and the Nigraha 0.4 probability threshold. Required paper-grade engines block promotion when they do not complete.
