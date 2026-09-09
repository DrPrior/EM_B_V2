# Decontainerization Plan

> **Status: PLANNING / IN PROGRESS.** No refactor code has landed yet. The repo
> still runs on Docker exactly as the (soon-to-be-legacy) docs describe. This
> document is the **canonical source of truth** for the migration off Docker —
> every other doc's "decontainerization" banner points here. Branch:
> `Decontainerize`.

## Why

Docker is no longer permitted on the organization's (UALR) machines, so the app
must run with **no container runtime at all**. Neo4j and the FastAPI API — the
only two things still in Docker — move to **native host processes**. Ollama is
already host-native and does not change.

## Current vs target architecture

**Current (Docker):**
```
Docker: Neo4j container + API container (uvicorn)   ── api reaches Ollama via host.docker.internal
Host:   Ollama (native, GPU)
Electron desktop app supervises the Docker stack (docker load / docker compose)
```

**Target (native, no Docker):**
```
Electron shell (supervisor)
   ├─ spawns  Neo4j        (native server + bundled JRE)   ── bolt 127.0.0.1:7687
   ├─ spawns  FastAPI/uvicorn (frozen exe or venv)          ── http 127.0.0.1:8000
   └─ ensures Ollama       (native, already present)         ── http 127.0.0.1:11434
```

`host.docker.internal` disappears — everything is `127.0.0.1`. That removes the
`OLLAMA_HOST=0.0.0.0` LAN exposure and the entire firewall-hardening burden: a
native API reaches Ollama on loopback, so Ollama returns to binding `127.0.0.1`
only. This is a security win, not just a lateral move.

## Key facts that make this feasible

- **`src/` is barely Docker-coupled.** The only Docker-isms are a default string
  (`data_root=/app/project_data`), docstrings mentioning `host.docker.internal`,
  and `DB_URI` being env-provided. See `src/core/config.py`,
  `src/services/ollama_bootstrap.py`.
- **No APOC / GDS dependency.** Vector search (`db.index.vector.queryNodes`,
  `vector.similarity.cosine`) is Neo4j core — native Neo4j needs no plugins.
- **`config.ollama_base_url` already defaults to `http://localhost:11434`**, so
  the native app works with defaults once the container override is dropped.
- The intent is pre-recorded in `HYBRID_SETUP.md` ("Run the API natively (the
  real long-term fix)… remains unbuilt; for a fleet of roaming, non-technical-
  user laptops it is still the preferred fix").

## The decision that drives everything: how to ship the runtimes

Fleet machines have **no Docker and IT blocks unsigned installers**. Everything
shipped must be signed or installer-free.

- **Python API — recommended: freeze with PyInstaller (one-dir) → `emb-api.exe`
  + `_internal/`, code-signed with the UALR certificate already being staged.**
  End users never touch Python/pip/venv; it's a folder to copy, not an
  installer. *Biggest technical risk: freezing `unstructured`* (optional parsers
  + data files PyInstaller misses). Validate a frozen build ingests PDF/PPTX/DOCX
  **before** committing to this. Alternative: ship embeddable CPython 3.12 + a
  pre-built `site-packages` as a plain folder (no installer).
- **Neo4j — ship the Community tarball + a bundled JRE**, unpacked (not a Windows
  service — that needs admin). Supervisor runs `neo4j console` as a child.

**This packaging choice is still OPEN — confirm before implementing Workstream D.**

## Workstreams

### A. App code (small, do first)
1. `DB_URI` → `bolt://127.0.0.1:7687` (env only; no code change —
   `src/database/connection.py` reads it from env).
2. Drop the `OLLAMA_BASE_URL=host.docker.internal` override; the
   `http://localhost:11434` default in `config.py` works natively.
3. `data_root` (`config.py`): change default off `/app/project_data` to a host
   path, or always pass via env. The `/files` citation endpoint resolves against
   it — must point at the real extracted corpus dir or downloads 404.
4. `ollama_bootstrap._PROJECT_ROOT` assumes `/app`; add a
   `sys.frozen`/`sys._MEIPASS`-aware lookup so the Modelfiles are found when
   frozen. Keep the Modelfiles next to the exe.

### B. Native dev stack (fast win, validates the app natively)
Replace `docker-compose.yml` with a native dev flow (or `scripts/dev-up.ps1`):
native Neo4j + `uvicorn src.main:app --reload` in a conda/venv + Ollama.
`.env`: `DB_URI=bolt://127.0.0.1:7687`, `NEO4J_AUTH`,
`DATA_ROOT=<repo>/project_data`. Run the pipeline directly
(`python -m pipeline.ingest`) instead of `docker exec`.

### C. Neo4j native
- **Version lock (hard):** the shipped `neo4j.dump` was exported from
  **2026.04.0**; `neo4j-admin database load` refuses a store-format mismatch, so
  the bundled native Neo4j must be the same 2026.04.0 line. Re-export the dump on
  any bump.
- **Password-before-init (hard):** today the random password is baked into the
  Docker volume on first init. Natively, the equivalent is the Neo4j **data
  directory** — set the password with `neo4j-admin dbms set-initial-password`
  **before first start**, then load the dump, or auth breaks the same way.
- Bundle a JRE (17/21 for this line); don't assume a host Java.

### D. Electron desktop rewrite (the bulk)
| File | Action |
|---|---|
| `electron/lib/docker.js` | **Delete** — no Docker detection/install/load. |
| `electron/lib/compose.js` | **Replace** with a native process manager (`neo4j.js`) that spawns/stops Neo4j + uvicorn. |
| `electron/supervisor.js` | Rewrite `start`/`stop`/`quickStart`: launch Neo4j → wait for bolt → launch API exe → poll `/health`; kill full process tree on quit (Windows `taskkill /T` or `tree-kill`). |
| `electron/lib/snapshot.js` | Keep `neo4j-admin database load`, but run **native** neo4j-admin (stop, load, restart) instead of `compose runOneOff`. |
| `electron/lib/firstrun.js` | Drop `docker` + `image` (docker load) steps; add `neo4j` + `runtime` steps. New order: `gpu → ollama → models → neo4j → runtime → data → snapshot → start`. |
| `electron/lib/envfile.js` | Keep random-password logic; emit **process env** for children, not compose-interpolation vars. Drop `APP_VERSION`/`PROJECT_DATA_DIR` compose-isms. |
| `electron/main.js` | Mostly unchanged — still loads `http://127.0.0.1:8000` once healthy. |

**Pitfall — process lifecycle:** Docker gave restart policies,
`depends_on: service_healthy` ordering, and clean teardown for free. Natively you
own startup ordering (Neo4j ready before API), crash detection/restart, orphan
cleanup on relaunch, and port-in-use collisions (7687/8000/7474) from a crashed
prior run. Use real readiness probes (bolt connect, not just process-alive).

### E. Build & release pipeline
Replace `Dockerfile`, `Dockerfile.prod`, and the image half of
`electron/scripts/build-release.ps1` (and `build-image.ps1`) with a
**PyInstaller build + signing** step. New shipped assets: signed API bundle,
Neo4j+JRE folder, `neo4j.dump`, `project_data.tar.gz`, Modelfiles. Update
`electron/resources/assets.manifest.json` + SHA-256 checks (drop `image` tar; add
runtime/neo4j entries). Keep the USB delivery model — it's orthogonal.

### F. Docs, tests, scripts
- `CLAUDE.md`, `docs/HYBRID_SETUP.md`, `electron/README.md`,
  `docs/TARGET_MACHINE_PREP.md`, `docs/USB_README.txt`: reframed to native (this
  pass). The firewall-hardening section becomes moot (loopback only).
- Tests: `docker exec … pytest` → `pytest` in the venv. Check
  `tests/integration/` for hardcoded `neo4j:7687` / `host.docker.internal`.
- `scripts/export-graph.ps1` / `import-graph.ps1`: drive native `neo4j-admin`.
- Retire `scripts/harden-ollama-firewall.ps1`.

## Top pitfalls (consolidated)
1. **Freezing `unstructured`** — the single biggest unknown; spike it first.
2. **Neo4j store-format version lock** to 2026.04.0; re-export on any bump.
3. **Neo4j password before first init**, then load dump.
4. **IT's unsigned-installer block** — sign everything or ship installer-free;
   gated on the UALR cert already being staged.
5. **Process supervision** you now own (ordering, readiness, restart, teardown,
   port collisions).
6. **Bundle Java** — don't assume a host JRE.
7. **Don't re-download/re-execute runtimes** on pre-provisioned machines
   (endpoint-security dropper pattern) — use in place, verify by hash.

## Suggested sequencing
1. **A + B** — app tweaks + native dev stack. Proves the app runs with zero
   containers.
2. **Packaging spike** — PyInstaller the API (confirm `unstructured` works
   frozen); bundle native Neo4j + JRE and load the dump by hand. De-risks the two
   unknowns before any Electron work.
3. **C + D** — Electron supervisor/wizard + build pipeline.
4. **E/F** — finish build pipeline, docs, tests, clean-machine first-run test.
