# AGENTS.md

YOLO + OpenCV webcam prototype for counting bus passengers. Plain scripts, no package, no build system, no automated tests.

## Setup

- Python 3.14 venv at `.venv` is git-ignored and not reproducible: there is **no** `requirements.txt`, lockfile, or `pyproject.toml`. Installed deps: `ultralytics` 8.4, `opencv-python` 5.0, `torch` 2.14 (CUDA 13).
- Recreate with: `python -m venv .venv && .venv/bin/pip install ultralytics opencv-python`.
- Weights are committed at the repo root: `yolo11n.pt` (used everywhere) and `yolo26n.pt` (unused). `detector_passageiros.py` resolves `yolo11n.pt` relative to its own file, so scripts work from any directory.

## Running

- Every script is standalone and interactive: it opens `cv2.VideoCapture(0)` and needs a GUI for `cv2.imshow`/`cv2.selectROI`. Nothing works headless or in CI. Quit with `q` (ESC in `getROILines.py`).
- `busScript.py` — the bus simulation and intended entrypoint: `p` stops/departs, `o` opens/closes doors, `q` quits. Detection runs **only** while stopped with doors open; the panel shows real-time occupancy vs `LIMITE` (40). Tune `LIMITE`, `PASSAGEIROS_INICIAIS`, and `SENTIDO_ENTRADA` at the top.
- `detector_passageiros.py` — passenger detector module: `DetectorPassageiros` (YOLO + ByteTrack line crossing) plus `lado_da_linha`/`cruza_segmento`. Tune `LINHA_*` and `MARGEM` at the top; `LADO_ENTRADA` is only the module default (the bus app overrides it via `SENTIDO_ENTRADA`). Line coordinates must match the camera resolution (currently 1280x720-style values).
- `getROI.py` / `getROILines.py` — one-shot calibration tools: freeze a frame, select a rectangle or two points, print coordinates to paste as constants into the detection scripts. Not part of runtime.
- Camera index `0` is expected to be the Iriun phone webcam; try `1`/`2` if the feed is black.

## Tests

- No test runner or pytest config exists. `test.py` is empty; `tests/` holds manual scratch scripts, not automated tests.
- `tests/webcamtest.py` — minimal YOLO + webcam smoke test; use it first to verify camera and model work.
- `tests/passtest.py` — ROI-entry demo with hardcoded ROI `(300,200)-(600,500)`.
- The integrated simulation is `busScript.py` at the repo root, not in `tests/`.

## Conventions

- Identifiers, comments, and UI strings are Portuguese (e.g., `detectar_passagem`, `pessoa_dentro`); keep that style.
- Counting logic uses person class `0`, ByteTrack (`model.track(..., persist=True)`), and "bounding-box center crossed the line segment" checks. Changing `model(...)` back to plain detection silently drops the `boxes.id` needed for counting.
- `DetectorPassageiros.resetar()` clears tracking state (not the counters); `busScript.py` calls it whenever doors open/close or the bus departs, so a stop never inherits crossings from the previous one.
- Line direction is set by `SENTIDO_ENTRADA` in `busScript.py` and passed to `DetectorPassageiros.processar(frame, lado_entrada=...)`; flipping it swaps entradas/saidas and therefore the occupancy total.
- The tree is mid-refactor: old root scripts now live under `tests/` and show as deleted in git, while `busScript.py`, `detector_passageiros.py`, and `getROI*.py` are untracked. Don't restore the deleted `script.py`/`passtest.py`/`webcamtest.py` copies.
