# AGENTS.md

YOLO + OpenCV webcam prototype for counting bus passengers. Classifies overcrowding, publishes readings to a local SQLite database, and exposes a dashboard with alerts and daily history. Standalone Python scripts: no package manager, build system, or test runner config.

## Setup

- Run scripts with `.venv/bin/python <script>` — `.venv` (Python 3.14) is the only interpreter with the deps. `.venv/bin/pip` is broken (its launcher points at the old `My Folders` path); use `.venv/bin/python -m pip` instead.
- No `requirements.txt`, lockfile, or `pyproject.toml`; recreate with `python -m venv .venv && .venv/bin/python -m pip install ultralytics opencv-python`.
- Installed deps: `ultralytics` 8.4.184, `opencv-python` 5.0.0, `torch` 2.14.1+cu130, `numpy` 2.5.4. `servidor.py`/`superlotacao.py`/`cliente_api.py` use only the stdlib on top of that.
- Weights are committed at the repo root: `yolo11n.pt` (the only one used) and `yolo26n.pt` (unused). `detector_passageiros.py` resolves its model relative to its own file; `tests/webcamtest.py` and `tests/passtest.py` use `YOLO("yolo11n.pt")` relative to the CWD, so run those from the repo root.

## Camera app (`busScript.py`)

- The intended entrypoint, interactive: `p` stops/departs, `o` opens/closes doors (only while stopped), `q` quits. Needs camera `0` and a GUI for `cv2.imshow`/`cv2.selectROI`; nothing here works headless or in CI. Camera `0` is expected to be the Iriun phone webcam; try `1`/`2` if the feed is black.
- At startup it reads the bus registry from the server (`GET /api/onibus`) and asks which bus this computer represents (numbered list, also accepts the exact name). `--onibus NOME` skips the prompt after validating the name; `--servidor URL` points at a non-default server. It exits with a message if the server is unreachable or the registry is empty — there is no hardcoded bus id anymore.
- Detection runs **only** while stopped with doors open. Tune `LIMITE` (capacity, 40), `PASSAGEIROS_INICIAIS`, and `SENTIDO_ENTRADA` at the top of the file. The route label (`linha`) comes from the selected bus's registry entry.
- Each loop it publishes to the chosen server as the selected bus/line, on every change plus a heartbeat every `INTERVALO_ENVIO` (10s). `cliente_api.ClienteLotacao` posts from a background thread with a 1-slot coalescing queue, so a stopped server never stalls the camera loop — never replace that with a blocking request in the loop.
- `detector_passageiros.py` — reusable detector: `DetectorPassageiros` (YOLO + ByteTrack line crossing) plus `lado_da_linha`/`cruza_segmento`. Tune `LINHA_*` and `MARGEM` here; direction is tuned via `SENTIDO_ENTRADA` in `busScript.py` (the module's `LADO_ENTRADA` is only a fallback). The constructor also accepts `linha`/`lado_entrada`/`margem`/`conf` for overrides. Line coordinates are absolute pixels tied to the capture resolution; recalibrate with `tools/getROILines.py`.
- `tools/getROI.py` / `tools/getROILines.py` — one-shot calibration tools: freeze a frame, select a rectangle or two points, and print constants to paste into the detector. Not part of runtime. `getROILines.py` quits with ESC; `r` resets the image; `getROI.py` closes on any key.

## Dashboard and API (`servidor.py`)

- `.venv/bin/python servidor.py` → dashboard at `http://127.0.0.1:8000/`, backed by `dados/onibus.db` (SQLite, created on startup, gitignored, WAL). Flags: `--porta`, `--banco`, `--host 0.0.0.0` (expose to phone/LAN), `--verboso`.
- Pages: `home.html` is the dashboard served at `/` (vanilla JS + canvas, no CDN); `onibus.html` is the bus registry served at `/onibus`. Both link the shared `estilo.css`, served at `/estilo.css`. Opening the HTML files via `file://` will not work because they fetch the API.
- `estilo.css` holds the whole theme (`:root` variables, layout, cards, tables, management form). It fixes the overscroll white edges with `html` background, `color-scheme: dark`, a fixed body background and `overscroll-behavior-y: none`; keep those when editing.
- Bus registry lives in the `onibus` table (`nome` PK, `linha`, `criado_em`, `atualizado_em`) in the same SQLite DB. On the first start with an older DB, existing distinct `leituras.onibus` are seeded into it once; deleting/recreating entries does not reseed. Readings from an unknown bus are auto-registered with `INSERT OR IGNORE` without overwriting a registered line.
- API: `POST /api/leituras` `{onibus, passageiros, capacidade, viagem, linha}`, `GET /api/estado?onibus=`, `GET /api/historico?onibus=&data=YYYY-MM-DD`, `GET /api/onibus`, `GET /api/saude`. `viagem` and `linha` are optional metadata; `linha` defaults to `""`. `/api/onibus` is registry-driven and adds per-bus `linhas`, `leituras`, `idade_segundos`, and `obsoleto`.
- Registry CRUD: `POST /api/onibus` `{nome, linha}` (201, 409 duplicate), `PUT /api/onibus/<nome>` `{nome, linha}` (rename cascades to `leituras.onibus`; 404 missing, 409 collision), `DELETE /api/onibus/<nome>` (removes only the registry entry and preserves historical readings). Names are URL-encoded in the path.
- Defaults for `GET /api/estado`/`GET /api/historico` without `onibus` use the registered bus with the most recent reading, so a bus deleted from the registry does not reappear through the defaults.
- The client sends only raw counts; `servidor.py` reclassifies with `superlotacao.classificar` (server is the source of truth). Don't accept a client-supplied level.
- The dashboard shows "DESCONECTADO" after `LIMITE_OBSOLETO` (60s) without a reading; the 10s heartbeat keeps it live while `busScript.py` runs. `/api/onibus` also returns `idade_segundos`/`obsoleto` per bus, so the selector labels each bus as conectado/desconectado.
- History responses include `resumo` (peak/average/alerts plus `onibus`/`linha`), `serie` downsampled to peaks, `alertas` (transitions into lotado/superlotado, each with `onibus`/`linha`), and the last 100 `leituras` with `onibus`/`linha` per row.
- `dados/onibus.db` may predate `linha`; `iniciar_banco()` runs `ALTER TABLE ... ADD COLUMN linha TEXT NOT NULL DEFAULT ''` automatically, so existing rows show an empty line.

### Using the dashboard

1. Start `.venv/bin/python servidor.py` and leave it running, then open `http://127.0.0.1:8000/` (use the machine's LAN IP and `--host 0.0.0.0` to view it from a phone).
2. Start `.venv/bin/python busScript.py` in another terminal and pick the bus this computer represents from the registry list (or pass `--onibus NOME`). The server alone does not produce data, so the page stays "SEM LEITURAS" until readings arrive. Register buses first on the "Gerenciar ônibus" page (`/onibus`) if the list is empty.

- The page polls `/api/onibus`, `/api/estado` and `/api/historico` every 3 s (`INTERVALO_ATUALIZACAO` in `home.html`); there is no WebSocket/SSE, so bus status is derived from reading age.
- Controls: the "Ônibus" `<select>` is rebuilt from `/api/onibus` when the bus/line set or any bus's `obsoleto` flag changes; options read `onibus — linha · conectado|desconectado`, and it defaults to the most recent bus. The "Data" input defaults to the browser's local today. Changing either refetches immediately.
- The "Gerenciar ônibus" link in the header opens the separate `/onibus` page, which polls `/api/onibus` every 5 s (`INTERVALO_ATUALIZACAO` in `onibus.html`). Its form uses the CRUD API to register, rename/relabel and delete buses; editing prefills the form, deleting asks for confirmation and keeps historical readings. The list refreshes on every poll, so a `busScript.py` starting on another machine appears without a page reload.
- The header pill follows the selected bus, not just the server: `ônibus conectado`, `ônibus desconectado` (stale), `sem leituras` (empty DB), or `servidor desconectado` (fetch failed).
- Banner: current level, "DESCONECTADO" when the latest reading is older than 60 s, or "SEM LEITURAS" on an empty DB; the detail line includes bus and line. Cards show current, day peak, day average and alert count (transitions into lotado/superlotado, not readings); the canvas plots % of capacity with dashed 70/100/120% lines (the series is peak-downsampled server-side).
- Alerts show bus · line and are newest-first. The history table has explicit **Ônibus** and **Linha** columns (empty line renders `—`), is newest-first, and is capped at 100 rows, so switching buses keeps the origin visible even though the API query is already filtered.
- `_arquivo()` re-reads `home.html`, `onibus.html` and `estilo.css` on every request, so editing any page needs only a browser refresh — no server restart.
- Dates are the server's local date (`datetime.now()`), not the browser timezone. A date with no rows returns `vazio: true` and empty everything.
- To exercise the dashboard without a camera, POST a reading (201 on success):
  `curl -s -X POST http://127.0.0.1:8000/api/leituras -H 'Content-Type: application/json' -d '{"onibus":"onibus-01","passageiros":42,"capacidade":40,"viagem":"teste","linha":"101"}'`
- To wipe test data, stop the server and `rm dados/onibus.db*`; it is recreated on the next start.

## Classification (`superlotacao.py`)

- Levels by fraction of capacity: `normal` <70%, `atencao` 70–99%, `lotado` 100–119%, `superlotado` ≥120%. `NIVEIS_ALERTA` = lotado + superlotado (what the dashboard calls an alert).
- `classificar()` returns `{nivel, rotulo, passageiros, capacidade, percentual}`; used by both the camera panel and the server. Thresholds live in `LIMIAR_*` — change them here, not in the dashboard.

## Tests

- `tests/teste_lotacao.py` — headless, no camera needed: classification boundaries, old-DB migration (adds `linha` and seeds the bus registry once), per-bus connected/disconnected status, registry CRUD (create/rename/delete, duplicate 409, missing 404, rename cascade, delete keeps readings), page serving (`/`, `/onibus`, `/estilo.css`) and a full API/SQLite/client roundtrip (bus/line/history/alerts) on an ephemeral port. Run `.venv/bin/python tests/teste_lotacao.py`.
- `tests/webcamtest.py` — minimal YOLO + webcam smoke test; use it first to verify camera and model work.
- `tests/passtest.py` — older ROI-entry demo with hardcoded ROI `(300,200)-(600,500)`.
- The integrated simulation is `busScript.py` at the repo root, not in `tests/`.

## Conventions

- Identifiers, comments, and UI strings are Portuguese (e.g., `detectar_passagem`, `pessoa_dentro`); keep that style.
- Counting uses person class `0` and ByteTrack (`model.track(..., persist=True)`). Replacing it with plain `model(...)` silently drops the `boxes.id` needed for counting.
- `DetectorPassageiros.processar()` returns per-frame `(annotated, entradas, saidas)`; its `.entradas`/`.saidas` attributes accumulate for the trip summary. `resetar()` clears tracking state but not counters, and `busScript.py` calls it whenever doors open/close or the bus departs so a stop never inherits crossings from the previous one.
- Direction comes from `SENTIDO_ENTRADA` in `busScript.py`, passed to `processar(frame, lado_entrada=...)`; the module's `LADO_ENTRADA` is only a default (it is `-1`, while `busScript.py` runs with `1`). Flipping it swaps entradas/saidas and therefore the occupancy change.
- Crossing uses deliberate hysteresis: points within `MARGEM` px of the line keep their previous side, and `FRAMES_PARA_ESQUECER` expires stale track IDs. Don't "simplify" this into a plain side check or jitter will be counted as crossings.

## Git

- Root `.gitignore` covers `dados/`, `*.db`, `*.db-wal`, `*.db-shm`, and `__pycache__/`. `__pycache__/detector_passageiros.cpython-314.pyc` was committed before that and is still tracked; don't `git add -A` blindly or commit bytecode churn.
