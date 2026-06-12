# Scripts

Operational scripts live here so the root stays focused on project configuration.

- `../install.sh` (repository root) installs all dependencies and starts Docker Compose services plus the local backend and frontend.
- `fetch_kepler_astronet.py` fetches the verified Kepler/K1 AstroNet checkpoint.
- `fetch_k2_exomac_kkt.py` fetches and registers the pretrained K2-capable ExoMAC-KKT artifact bundle.
- `fetch_nigraha_weights.py` fetches the registered TESS/Nigraha artifacts.
- `build_dave_modshift.sh` clones the official DAVE repository at the pinned commit and compiles the `vetting/modshift` executable required by paper-grade model-shift vetting.
- `run_orbitlab_science_benchmark.py` runs the science benchmark harness and writes JSON/Markdown reports.
- `build_release_room.py` builds the Science Provenance Release Room packet for a release tag, including benchmark deltas, model checksums, calibration checksums, SPDX SBOM data, release asset checksums, and a zipped packet.
- `export_evidence_packet.py` exports per-analysis evidence from a stored analysis result.
- `register_astronet_artifact.py` registers external AstroNet-compatible artifacts.
- `predict_kepler_astronet_tf.py` runs Kepler inference inside a TensorFlow 1.x Docker runtime.
- `convert_kepler_astronet_npz.py` converts the Kepler checkpoint when a converter Docker image is available.
- `generate_nigraha_golden.py` regenerates Nigraha parity fixtures when the original Keras runtime script/image is available.
- `dump_repo.py` writes a compact source/config/docs dump to `.orbitlab/scratch/repodump.txt`.
- `frontend/scripts/capture-demo-assets.mjs` is exposed through `npm run capture:demo-assets --prefix frontend` and regenerates README screenshots/GIFs from a mocked UI demo flow.

Run scripts from the repository root unless the script says otherwise.
