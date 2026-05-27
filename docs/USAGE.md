# OrbitLab Usage Guide

This guide walks through running OrbitLab and using the main workflow with real mission data. OrbitLab is intentionally conservative: it shows BLS and analysis candidates only when they come from the selected product and pipeline, not from illustrative placeholder data.

## 1. Start The App

Install dependencies once:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,science,api,ml]"
npm ci --prefix frontend
```

Start the full local stack:

```bash
scripts/start_all.sh
```

The script starts Docker services, the FastAPI backend, and the Vite frontend. It prints the local URLs when startup completes:

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`

Logs and pid files are written under `.orbitlab/`.

## 2. Open It From Another Computer On Your LAN

Start the app bound to all network interfaces:

```bash
FRONTEND_HOST=0.0.0.0 BACKEND_HOST=0.0.0.0 scripts/start_all.sh
```

Find this machine's LAN address:

```bash
ip -brief addr
```

Open the frontend from another computer using the LAN address, for example:

```text
http://192.168.1.39:5173
```

If the page does not load from the other computer, check that both computers are on the same network and that the firewall allows ports `5173` and `8000`.

## 3. Search For A Target

1. Choose a mission: `TESS`, `Kepler`, or `K2`.
2. Enter a target query in the search box.
3. Click `Search`.
4. Select a target from `Matches`.

Good demo queries are listed in [DEMO_TARGETS.md](DEMO_TARGETS.md). Practical starting points include:

- `TIC 307210830` with mission `TESS`
- `Kepler-10` with mission `Kepler`
- `TOI-700` with mission `TESS`
- `EPIC 201367065` with mission `K2`

Common famous-name aliases can appear under `Suggested targets`. For example, `trappist`, `trappist 1`, `trappist-1`, and `trappist1` suggest `TRAPPIST-1`. OrbitLab does not silently auto-select the alias; click the suggestion to fetch products for the canonical target.

## 4. Select A Product

After selecting a target, OrbitLab lists available target pixel products. Pick one product before opening the aperture editor, running BLS preview, or running full analysis.

Product discovery uses real MAST/Lightkurve results. The first product lookup or download can take time, especially on a fresh machine.

## 5. Optional: Create An Aperture Mask

1. Click `Aperture`.
2. Select one or more bright pixels in the preview.
3. Click `Apply Mask`.

The selected mask is used by the next BLS preview or analysis run. If you do not create a custom mask, OrbitLab uses the pipeline/default aperture path.

## 6. Run BLS Search

1. Click `BLS Search`.
2. Adjust the period range if needed.
3. Click `Run Preview Search`.

When candidates are found, the UI shows:

- Candidate cards in the left rail.
- Candidate orbit labels in the center simulation.
- A BLS power periodogram.
- A folded curve for the selected candidate.
- A light-curve timeline.

If the center simulation only shows the star, no candidates are currently loaded. That is expected before BLS or analysis runs, and the center overlay will say: `Run BLS Search or Analysis to render candidate orbits.`

## 7. Run Full Analysis

Click `Run Analysis` after selecting a product. The default run is Accuracy/Paper-grade mode: it stores a result and adds validation, physics, habitability, TLS, Wotan, DAVE, catalog-contamination, TRICERATOPS, and model context where the selected mission supports them.

The ML panel is intentionally honest about missing artifacts. Use `ML Status` to see whether each mission-specific model is ready, unavailable, or missing setup.

## 8. Save, Restore, And Export

- Click the save icon to save the current session.
- Click `Sessions` to restore a saved session.
- Click export after a full analysis result exists.

Preview-only BLS results are useful for exploration, but report export is available only after a full analysis.

## 9. Troubleshooting

- `No matching targets found`: try a known target from [DEMO_TARGETS.md](DEMO_TARGETS.md), confirm the mission, and check MAST connectivity.
- `No target pixel products found`: try another mission/product target, or wait and retry if MAST is slow.
- Star-only simulation: run BLS Search or full Analysis; OrbitLab does not draw fake orbits before candidates exist.
- LAN page does not load: bind to `0.0.0.0`, open `http://<LAN-IP>:5173`, and allow ports `5173` and `8000`.
- Model is unavailable: run the relevant fetch script shown in `ML Status` or in [model_artifacts.md](model_artifacts.md).
