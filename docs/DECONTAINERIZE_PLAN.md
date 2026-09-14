# Decontainerization Plan

> **Status: API DONE — packaging & Electron remain.** The Python API and the
> dev/pipeline flow now run fully native (no container assumptions). What's left
> is shipping it to end users without Docker: **freeze the API**, **bundle native
> Neo4j**, and **rewrite the Electron shell**. This doc is the canonical source of
> truth; every other doc's "decontainerization" banner points here. Working
> branch: `Decontainerize`.

## Why

Docker is no longer permitted on the organization's (UALR) machines, so the app
must run with **no container runtime at all**. Neo4j and the FastAPI API — the
only two things that were in Docker — move to **native host processes**. Ollama
was always host-native.

## Target architecture

```
Electron shell (supervisor)
   ├─ spawns  Neo4j        (native server + bundled JRE)   ── bolt 127.0.0.1:7687
   ├─ spawns  FastAPI API  (frozen exe; uvicorn in dev)     ── http 127.0.0.1:8000
   └─ ensures Ollama       (native, already present)         ── http 127.0.0.1:11434
```

Everything is `127.0.0.1`. `host.docker.internal` is gone, which also removes the
`OLLAMA_HOST=0.0.0.0` LAN exposure and the entire firewall-hardening burden —
Ollama returns to binding loopback only.

## Progress

**Landed (on `Decontainerize`):**
- **A — app native-safety:** `DB_URI`/`DATA_ROOT` env-driven; POSIX-normalized
  `File.filepath`; `config` `extra="ignore"`; `_file_url` separator-robust; the
  `graph.py` syntax fix.
- **B — native dev stack:** `.env.example` native-first, `scripts/dev-up.ps1`,
  `docs/NATIVE_DEV.md`. Neo4j runs via Neo4j Desktop in dev.
- **Embedding swap:** `qwen3-embedding:4b` (2560-d) → `embeddinggemma:latest`
  (768-d); vector index + Modelfile + config + tests updated.
- **Parallel enrichment:** Pass 2 thread-pooled (`enrichment_concurrency`,
  default 4) — ~2.3× on the RTX 4000, ~10 h → ~4.5 h.
- **`cryptography` dependency** added (AES-encrypted PDFs were silently dropped).
- **API decontainerization finish:** admin endpoints default to `settings.data_root`;
  container references removed from docstrings; **`src/core/paths.py`** added with
  `sys.frozen`/`_MEIPASS`-aware `resource_root()`/`modelfile_path()`/`static_dir()`,
  and `ollama_bootstrap` + `main.py` now resolve Modelfiles and the static UI
  through it (frozen-ready). The Docker files (`Dockerfile*`, `docker-compose*.yml`)
  were deleted.
- Graph **rebuilt** on native Neo4j (`2026.07.01`): 10,360 chunks at 768-d, vector
  index `chunk_vector_idx` ONLINE.

**Remaining: C (bundle Neo4j), D (Electron rewrite), E (build pipeline).**

> ⚠️ **The Electron app is currently non-functional.** It still references the
> deleted Docker artifacts — `electron/package.json` lists
> `../docker-compose.desktop.yml` in `extraResources` (so `npm run dist` fails),
> and `lib/docker.js` / `lib/compose.js` / `lib/snapshot.js` / `lib/firstrun.js` /
> `supervisor.js` are Docker-wired. It must be rewritten (Workstream D) before it
> runs again.

## How the runtimes ship

Fleet machines have **no Docker and IT blocks unsigned installers** — everything
shipped must be signed or installer-free.

- **Python API — PyInstaller one-dir → `emb-api.exe` + `_internal/`, code-signed
  with the UALR cert.** End users copy a folder, not run an installer.
  - **The biggest freeze risk is gone:** `unstructured` is declared in
    `requirements.txt` but **never imported** — the code parses with
    `pypdf` / `python-docx` / `python-pptx` (+ `cryptography`). Dropping
    `unstructured` removes the optional-parser/data-file freeze hazard; the
    remaining parsers freeze cleanly.
- **Neo4j — Community zip + bundled JRE**, unpacked (no admin service install).
  Supervisor runs `neo4j console` as a child.

## Remaining workstreams (detail)

### C. Bundle native Neo4j + JRE
- Ship **Neo4j Community (unpacked zip) + a bundled JRE 17/21** under the app's
  resources; no admin installer.
- **Store-format version = `2026.07.01`.** A **new dump is being regenerated** from
  the live `2026.07.01` dev DB, so bundle that same Neo4j line — `neo4j-admin
  database load` refuses a store-format mismatch. (Supersedes the old `2026.04.0`
  dump in `release/`.)
- First-run order: `neo4j-admin dbms set-initial-password <random>` **before** the
  first start → `neo4j-admin database load` the dump (offline) → `neo4j console`.
  Password-before-init is mandatory or auth breaks (same trap the Docker volume had).
- Config: bind bolt + http to `127.0.0.1`; data dir + modest heap/pagecache under
  the app's userData dir.

### D. Electron desktop rewrite (the bulk)
| File | Action |
|---|---|
| `electron/lib/docker.js` | **Delete** — no Docker detect/install/load. |
| `electron/lib/compose.js` | **Replace** with a native process manager (`lib/procs.js`): spawn/stop `neo4j console` + `emb-api.exe`, with bolt / `/health` readiness probes. |
| `electron/supervisor.js` | Rewrite `start`/`stop`/`quickStart`: Neo4j → wait bolt → API → poll `/health`; kill child trees on quit (`taskkill /T /F` or `tree-kill`); orphan + port-in-use cleanup (7687/8000/7474). |
| `electron/lib/snapshot.js` | Keep `neo4j-admin database load`, but drive the **bundled native** neo4j-admin (stop→load→start), not `compose runOneOff`; marker keyed on data-dir path. |
| `electron/lib/firstrun.js` | New step order `gpu → ollama → models → neo4j → runtime → data → snapshot → start`; drop the `docker` and `image` (`docker load`) steps; add `neo4j` (unpack + set password) and `runtime` (unpack API bundle) steps. |
| `electron/lib/envfile.js` | Keep the stable random password; emit **process env** for children (`NEO4J_AUTH`, `DB_URI=bolt://127.0.0.1:7687`, `DATA_ROOT=<extracted corpus>`); drop compose vars (`APP_VERSION`, `PROJECT_DATA_DIR`). |
| `electron/lib/ollamaenv.js` | **Drop `OLLAMA_HOST=0.0.0.0`** (native API → loopback); keep `KEEP_ALIVE=-1`, `NUM_PARALLEL` (parallel enrichment), `MAX_LOADED_MODELS`, flash-attn/kv-cache, `IGPU_ENABLE`. Retires the firewall-hardening story. |
| `electron/lib/paths.js` | Drop `composePath()`; add `neo4jDir()`, `apiExeDir()`, `jreDir()`. |
| `electron/main.js` | Mostly unchanged — loads `127.0.0.1:8000` on healthy; before-quit stops the native procs. |
| `lib/ollama.js`, `modelfile.js`, `gpu.js`, `assets.js`, `download.js`, `exec.js` | Largely reusable as-is (`ollama.js` VARIANTS already point at `embeddinggemma:latest`). |

**Pitfall — process lifecycle:** Docker gave restart policies,
`depends_on: service_healthy` ordering, and clean teardown for free. Natively you
own startup ordering (Neo4j ready before API), crash detection/restart, orphan
cleanup on relaunch, and port-in-use collisions. Use real readiness probes (bolt
connect + `/health`, not just process-alive).

### E. Build & release pipeline + packaging cleanup
- **Freeze entry point:** add `run_api.py` calling `uvicorn.run(src.main.app,
  host="127.0.0.1", port=8000)` — pass the app object (not the import string),
  no `--reload`, so it works frozen.
- **PyInstaller `.spec`** (checked in): one-dir; `--add-data` places `Modelfile`,
  `Modelfile.embeddings`, and `src/static` under the resource root — the exact
  contract `src/core/paths.py` expects. Expect `--collect-submodules uvicorn`
  (+ hidden imports) for uvicorn's dynamic loop/protocol/logging imports.
- **`requirements.txt`:** drop unused `unstructured`.
- **`electron/scripts/build-release.ps1`:** replace the `docker build`/`docker
  save` half with a PyInstaller run (zip the API bundle) + stage the Neo4j+JRE
  zip; keep the **re-exported** `neo4j.dump` + `project_data.tar.gz`.
- **`electron/package.json`:** remove the `../docker-compose.desktop.yml`
  `extraResources` entry (deleted file → breaks builds); fix the "Provisions
  Docker…" description; bump version. Signing (`win.signtoolOptions`) is
  configured — needs the cert.
- **`electron/resources/assets.manifest.json` + `lib/assets.js`:** drop the
  `image` tar entry; add `apiBundle` + `neo4j` entries with SHA-256; update
  verification. Delete the stale `release/emb-hybrid-api-*.tar.gz`.
- **Delivery/docs:** `scripts/stage-usb.ps1`, `docs/USB_README.txt`,
  `docs/TARGET_MACHINE_PREP.md` — drop Docker install/prep; ship the API bundle +
  Neo4j as assets; update the first-run step list. Retire the firewall-hardening
  section in `HYBRID_SETUP.md`. `scripts/export-graph.ps1`/`import-graph.ps1` →
  drive native `neo4j-admin`.

## Top pitfalls (consolidated)
1. **Neo4j store-format version lock** — bundle `2026.07.01` to match the new dump.
2. **Neo4j password before first init**, then load.
3. **IT's unsigned-installer block** — sign the API exe *and* the installer;
   gated on the UALR cert being staged.
4. **Process supervision** you now own (ordering, readiness, restart, teardown,
   orphans, ports).
5. **Bundle a JRE** — don't assume host Java.
6. **Don't re-download/re-execute runtimes** on pre-provisioned machines
   (endpoint-security dropper pattern) — use in place, verify by hash.
7. **Size** — API bundle + Neo4j + JRE + models + corpus grows the installer/USB.

(`unstructured` freeze risk — retired: the dep is unused and being dropped.)

## Suggested sequencing
1. **Packaging spike (low risk now):** drop `unstructured`; write `run_api.py` +
   the PyInstaller spec; prove the frozen exe serves the UI and ingests
   PDF/PPTX/DOCX.
2. **Bundle Neo4j + JRE**; set password, load the (new `2026.07.01`) dump, start
   natively by hand.
3. **Electron rewrite** — procs/supervisor/firstrun/snapshot/envfile/ollamaenv/
   paths; delete `docker.js`.
4. **Build pipeline** — `build-release.ps1`, `package.json`, manifest, signing.
5. **Docs + a clean-machine first-run test.**
