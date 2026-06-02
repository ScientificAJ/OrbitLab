# Published Checkpoints

Status: current for OrbitLab `v0.2.0`; release-level checksum evidence is also captured in the Science Provenance Release Room described in `docs/RELEASE.md`.

## Nigraha TESS Weights

The real published checkpoint set currently wired into OrbitLab is the Nigraha TESS ensemble:

- Repository: `https://github.com/ExoplanetML/Nigraha`
- Commit: `c4365b41dd02b187c3210189ffe8e3ead584f4f5`
- Path: `models/weights/global_nodropout/binary/`
- Files: `models_1.hdf5` through `models_10.hdf5`
- Model family: TESS CNN inspired by AstroNet/ExoNet-style global/local views, published with the Nigraha paper.
- Input contract from the released code: `global_view` `(1, 201, 1)`, `local_view` `(1, 81, 1)`, `odd_even_view` `(1, 162, 1)`, plus configured stellar/transit scalar features.

Fetch and register:

```bash
scripts/fetch_nigraha_weights.py
```

The script downloads the ten `.hdf5` files from GitHub raw URLs pinned to the commit above, verifies per-file SHA-256 hashes, then registers the ensemble directory in `.orbitlab/models.json`.

## Kepler AstroNet Checkpoint

OrbitLab also knows how to fetch the pinned Kepler checkpoint from `bibinthomas123/Astronet`:

- Repository: `https://github.com/bibinthomas123/Astronet`
- Commit: `9809ce92306f11fbdc96f9830b522026710a3883`
- Model id: `kepler-astronet-cnn-bilstm-attention`
- Files: `model.ckpt-20000.data-00000-of-00001`, `model.ckpt-20000.index`, `model.ckpt-20000.meta`

Fetch and register:

```bash
scripts/fetch_kepler_astronet.py
```

The fetcher uses GitHub media URLs so Git LFS objects resolve to checkpoint bytes, rejects LFS pointer files, and verifies each downloaded object hash before registration. Runtime inference uses `scripts/predict_kepler_astronet_tf.py` inside the TensorFlow 1.5 Docker image, so TensorFlow is not imported by the API process.

## K2 ExoMAC-KKT Artifact

OrbitLab uses ExoMAC-KKT as the registered K2 replacement artifact instead of exposing a separate K2 AstroNet unavailable entry:

- Repository: `https://huggingface.co/ZapatoProgramming/ExoMAC-KKT`
- Commit: `5cda5310d5a163679c6915f9463a4d6afc312483`
- Model id: `k2-exomac-kkt-randomforest`
- Model family: sklearn RandomForest candidate classifier trained on NASA Kepler, K2, and TESS catalog features.
- Files: `exoplanet_best_model.joblib`, `exoplanet_feature_columns.json`, `exoplanet_class_labels.json`, `exoplanet_metadata.json`

Fetch and register:

```bash
scripts/fetch_k2_exomac_kkt.py
```

This is not a light-curve CNN checkpoint. It is a no-training tabular ML replacement for K2 candidate vetting, using period, duration, depth, SNR, optional stellar properties, and derived catalog features.
