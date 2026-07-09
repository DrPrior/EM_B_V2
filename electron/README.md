# EM Knowledge Assistant — Desktop app

Electron wrapper that turns the EM_B_Hybrid stack into a one-click desktop app
for **Windows** and **macOS**. It is a *supervisor + first-run installer* around
the existing Docker stack — the FastAPI backend and its container internals are
unchanged. Electron:

1. On **first run**, guides the user through provisioning: Docker Desktop →
   Ollama → language models (~10 GB) → the prebuilt API image → the source
   corpus → the knowledge-graph snapshot → starting the stack.
2. On **later runs**, waits for Docker + Ollama and brings the stack up.
3. Loads the existing web UI at `http://127.0.0.1:8000` in its window.

**Delivery: USB drive, no download server.** The three heavy *custom* assets
(API image tar, graph snapshot, corpus) ship in an `assets/` folder on the USB,
read locally at setup time — the USB only needs to be plugged in during first
run. The targets are **online**, so everything else (Docker Desktop installer,
Ollama installer, and the ~10 GB base models) is fetched from official sources.
Docker and Ollama are installed only if missing (detection per machine).

Ollama stays **host-native** (not in Docker) so it uses the GPU. GPU
acceleration is Ollama's job and auto-detected: CUDA (Nvidia), Vulkan (Intel
Arc / iGPU — experimental), Metal (Apple Silicon), or CPU fallback.

## Layout

```
electron/
  main.js            app lifecycle + window; runs wizard or fast-start, then
                     navigates to http://127.0.0.1:8000
  preload.js         contextIsolated bridge (window.api)
  supervisor.js      compose up/down, /health polling, quickStart fast path
  lib/
    firstrun.js      guided first-run orchestrator (the step sequence)
    assets.js        locate the USB `assets/` folder (auto-detect + verify)
    docker.js        detect/install Docker, load image, run compose
    ollama.js        detect/install Ollama, pull bases + build variants (streamed)
    modelfile.js     Node port of ollama_bootstrap._parse_modelfile
    snapshot.js      Node port of scripts/import-graph.ps1 (offline dump load)
    compose.js       shared `docker compose --env-file … -f …` invocation
    envfile.js       per-install desktop.env (random, stable Neo4j password)
    download.js      streaming downloader w/ progress + SHA-256 verify + cache
    gpu.js           best-effort GPU detection (messaging only)
    paths.js         userData + bundled-resource locations
  wizard/            offline setup UI (html/css/js), no CDN
  resources/
    assets.manifest.json   URLs + checksums for the heavy download assets
  scripts/
    build-release.ps1      build image tar + snapshot + corpus, update manifest
    vendor-assets.ps1      refresh src/static/vendor (Tailwind, marked)
```

Related files at the repo root: `docker-compose.desktop.yml` (production compose,
prebuilt image + generated env), `Dockerfile.prod` (lean runtime image),
`.env.example`.

## Preparing a USB drive (maintainer)

Two build steps, then copy onto the stick. **Order matters**: build the assets
first (it updates the manifest), then build the installers (they bake the
manifest in).

### 1. Build the custom assets

Do this on a machine that has a **fully built, enriched graph** (ran
ingest → load_manifest → enrich) and the `project_data/` corpus on disk.

```powershell
pwsh -File electron/scripts/build-release.ps1 -Version 0.1.0
```

This produces in `release/`:

| File | How the app uses it |
|---|---|
| `emb-hybrid-api-0.1.0.tar.gz` | `docker load`ed on first run (the API image) |
| `neo4j.dump` | imported into the Neo4j volume on first run |
| `project_data.tar.gz` | extracted + bind-mounted read-only (citation downloads) |

It also records each file's name + SHA-256 in
`electron/resources/assets.manifest.json` (verified off the USB at setup time).
`image.version` must equal the image tag (`emb-hybrid-api:<version>`) and the
`APP_VERSION` the desktop compose interpolates — the script keeps them in sync.
Docker/Ollama installers and the base models are fetched online, so they are not
in this bundle.

### 2. Build the installers

```bash
cd electron
npm install
npm run dist:win     # NSIS .exe   (run on Windows)
npm run dist:mac     # .dmg        (run on macOS)
```

Output lands in `electron/dist/`. Builds are **unsigned** for now — users get an
"unidentified developer" warning (Windows SmartScreen → *More info → Run anyway*;
macOS → right-click *Open*). See *Deferred* below.

### 3. Lay out the USB drive

```text
USB drive
  EM Knowledge Assistant-Setup-0.1.0.exe   (and/or the .dmg)
  assets/                                   ← the whole release/ folder
    emb-hybrid-api-0.1.0.tar.gz
    neo4j.dump
    project_data.tar.gz
```

The app auto-detects `assets/` (removable drives, or next to the installer). If
it can't, it shows a folder picker — the user selects the `assets` folder. The
folder is validated (must contain the image tar) and remembered, so an
interrupted setup resumes without re-picking.

## Develop / smoke-test the shell

```bash
cd electron
npm install
npm start
```

In dev, bundled resources resolve from the repo root instead of
`resourcesPath`. To exercise the real first-run flow you need the release assets
built; point the app at them with `EMB_ASSETS_DIR=<path to release/>` (or let the
picker find them). To re-trigger first-run, delete the markers under the app's
userData dir: `first-run-complete.json`, `graph-imported.json`,
`data-ready.json`, `desktop.env`, `assets-dir.json`.

## First-run flow details

- **Setup assets**: the image tar, snapshot, and corpus are read from the USB
  `assets/` folder — auto-detected (removable drives / next to the app / a saved
  path / `$EMB_ASSETS_DIR`) or chosen via a folder picker, then verified against
  the manifest SHA-256s. The USB is only needed during first run.
- **Docker**: silent install isn't possible on Windows (admin + WSL2 + reboot).
  The wizard downloads and launches the official installer, then waits for the
  daemon. If a reboot is needed it shows a "finish installing and reopen" banner;
  provisioning **resumes** on the next launch (every step is idempotent).
- **Ollama**: installed via the official installer, then the wizard pulls the
  base models and builds the `chat-model` / `embedding-model` variants with a
  progress bar (`/api/pull` + `/api/create`, streamed). Because the variants are
  built here, the API container's own startup bootstrap hits its instant warm
  path.
- **Credentials**: a random Neo4j password is generated once into `desktop.env`
  and reused forever (it's baked into the `em_b_v2_neo4j_data` volume on first
  DB start). Neo4j and the API bind to `127.0.0.1` only.
- **Graph**: the snapshot is loaded offline (Neo4j stopped) via a throwaway
  `compose run` container — the slow ingest/enrich pipeline is skipped entirely.
  The snapshot's Neo4j version is pinned to `neo4j:2026.04.0` (store format must
  match); bump it in `docker-compose.desktop.yml` and re-export if you upgrade.

## Verification (per plan)

On a clean machine/VM:

1. **Windows + Nvidia** — install → wizard completes → chat streams an answer →
   a citation link downloads its source file (validates the `project_data`
   mount). Confirm GPU use with `ollama ps`.
2. **Windows + Intel Arc / iGPU** — completes and answers (Vulkan or CPU
   fallback), even if slower.
3. **Windows, no GPU** — CPU fallback works; wizard reports "CPU" acceleration.
4. **macOS (Apple Silicon)** — completes with Metal.
5. **Restart** — quit + relaunch: wizard is skipped, stack comes up from the
   persisted volume, UI works offline (vendored Tailwind/marked).
6. **Backend tests** unchanged: `docker exec <api-container> pytest` against the
   *dev* image (the prod image is runtime-only and omits pytest).

## Deferred (structured, no rework)

- **Code signing / notarization**: add `win.certificateFile` /
  `mac.notarize` in `package.json` `build` — config only.
- **Auto-update**: add `electron-updater` + an update feed. The versioned image
  tag + manifest already support shipping new backends.
