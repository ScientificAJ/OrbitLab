# Scripts

Operational scripts live here so the root stays focused on project configuration.

- `start_all.sh` starts Docker Compose services plus the local backend and frontend.
- `fetch_kepler_astronet.py` fetches the verified Kepler/K1 AstroNet checkpoint.
- `fetch_k2_exomac_kkt.py` fetches and registers the pretrained K2-capable ExoMAC-KKT artifact bundle.
- `fetch_nigraha_weights.py` fetches the registered TESS/Nigraha artifacts.
- `register_astronet_artifact.py` registers external AstroNet-compatible artifacts.
- `predict_kepler_astronet_tf.py` runs Kepler inference inside a TensorFlow 1.x Docker runtime.
- `convert_kepler_astronet_npz.py` converts the Kepler checkpoint when a converter Docker image is available.
- `generate_nigraha_golden.py` regenerates Nigraha parity fixtures when the original Keras runtime script/image is available.
- `dump_repo.py` writes a compact source/config/docs dump to `.orbitlab/scratch/repodump.txt`.

Run scripts from the repository root unless the script says otherwise.
