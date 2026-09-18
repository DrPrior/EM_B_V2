# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ## ⚠️ Decontainerization: code done, release artifacts remain
>
> The organization (UALR) no longer permits Docker, so the app runs as **native
> host processes** — no container runtime at all, every service on `127.0.0.1`.
>
> **The Docker files are gone from this repo** (`Dockerfile`, `Dockerfile.prod`,
> `docker-compose.yml`, `docker-compose.desktop.yml` were deleted in `fdb0c6e`).
> The Python API, the pipeline, the dev flow, the Electron shell, and the build
> scripts are all native today. `docker compose up` / `docker exec` no longer
> work — if you find a doc or comment that tells you to run them, it is stale.
>
> - **Canonical plan + pitfalls:** [`docs/DECONTAINERIZE_PLAN.md`](docs/DECONTAINERIZE_PLAN.md) — read before migration work.
> - **Dev runbook:** [`docs/NATIVE_DEV.md`](docs/NATIVE_DEV.md).
> - **Landed:** A (app native-safety), B (native dev stack), D (Electron native
>   supervisor + first-run), E (freeze spec + build/release scripts). `lib/docker.js`
>   and `lib/compose.js` are deleted; [electron/lib/procs.js](electron/lib/procs.js) spawns Neo4j and the
>   frozen API directly.
> - **Remaining is artifact work, not code:** Workstream C (a **Community** Neo4j
>   plus a redistributable JRE staged for `build-release.ps1`, and a
>   Community-loadable *record/aligned* dump — the dev graph lives on
>   **Enterprise**, whose `block` store format Community refuses to load), then
>   code-signing (no UALR cert yet) and a clean-machine first-run test.
> - **⚠️ `dist/emb-api/emb-api.exe` cannot be run on this machine.** Defender ASR
>   rule `01443614-CD74-433A-B99E-2ECDC07BFC25` ("block executable files unless
>   they meet a prevalence, age, or trusted list criterion") is in Block mode
>   under UALR policy, so launching it gives a bare `Access is denied.` with no
>   traceback and nothing in AppLocker. Confirm with `Get-WinEvent -LogName
>   "Microsoft-Windows-Windows Defender/Operational" | Where-Object Id -eq 1121`.
>   The freeze can be *built* and inspected here, not executed. Don't chase it as
>   a Python or PyInstaller bug.
> - **Do not add new Docker coupling.** No `host.docker.internal`, no compose, no
>   `/app/...` paths in new code.
>
> Working branch: `Decontainerize` — cut task branches from it and PR back into
> it, not into `main` (`main` trails it by many commits).

## Stack

- **FastAPI** served by uvicorn as a native process on `127.0.0.1:8000` (a venv/conda env today; a frozen exe once Workstream E lands)
- **Neo4j** — native server (needs a JRE 17/21), bolt on `127.0.0.1:7687`, browser on `127.0.0.1:7474`. Neo4j Desktop is the dev path; a bundled tarball is the ship path.
- **Ollama** — native on the host, using the host GPU (Metal/CUDA/Vulkan) directly, on `127.0.0.1:11434`. Because the API is also native it reaches Ollama over plain `localhost`; Ollama does **not** need `OLLAMA_HOST=0.0.0.0` (that requirement existed only because the API was containerized).
- **Static web UI** — chat interface served at `/` from [src/static/](src/static/) (index.html, app.js, style.css, vendored marked + tailwind — no CDN).

The app calls custom Modelfile-built variants, never the base models directly:
`chat-model` (FROM `gemma4:12b-it-qat`, `num_ctx 8192`) for chat and entity
extraction, `embedding-model` (FROM `embeddinggemma:latest`, **768-dim**) for
embeddings. Names live in [src/core/config.py](src/core/config.py); the variants are pulled and
built on the host automatically at API startup by
[src/services/ollama_bootstrap.py](src/services/ollama_bootstrap.py) over HTTP.

Neo4j, the API, and Ollama must all be up for the app to function.

## Common Commands

Prerequisites: native Neo4j listening on bolt 7687, host Ollama running, and a
`.env` (copy [.env.example](.env.example)). See [docs/NATIVE_DEV.md](docs/NATIVE_DEV.md) for the first-time setup.

**Start the API (preferred):**
```powershell
scripts/dev-up.ps1            # -Port 8000, -NoReload
```
This loads `.env` into the **process** environment, pre-flights Ollama and Neo4j,
then runs `uvicorn src.main:app --reload --host 127.0.0.1`. Loading `.env` into
the process matters: [src/database/connection.py](src/database/connection.py) reads `NEO4J_AUTH` and
`DB_URI` from `os.environ` directly, and pydantic-settings' `.env` support does
**not** populate `os.environ`. Running bare `uvicorn src.main:app --reload`
works only if those two vars are already exported.

On startup the API verifies Neo4j, creates constraints + the vector index, waits
for Ollama, then pulls base models and builds the custom variants if missing.
It **fail-fasts** — no Ollama means the app exits rather than serving broken chat.

**Re-provision models without restarting:**
```powershell
curl.exe -s -X POST http://localhost:8000/admin/bootstrap-models
```

**Trigger ingestion on demand:**
```powershell
curl.exe -s -X POST http://localhost:8000/admin/ingest | python -m json.tool
```

**Full rebuild order** (drop graph → ingest → load manifest → enrich):
```powershell
python -m pipeline.ingest
python -m pipeline.load_manifest
python -m pipeline.enrich
```
`load_manifest` must run **after** `ingest` so its filename-based matching finds
the ingested File nodes. Run it earlier and manifest rows whose category column
doesn't match an on-disk folder (most of MANIFEST2.md) create duplicate catalog
nodes at synthetic paths.

**Tests** (in your env — no `docker exec` anymore):
```powershell
pytest                            # unit only; integration excluded by pyproject addopts
pytest tests/unit/test_rag.py -v  # single file
pytest tests/unit/test_rag.py::test_name -v
pytest -m integration             # requires live Neo4j + Ollama + API
pytest -m ""                      # everything
```

**Lint / format:**
```powershell
ruff format .
ruff check .
```

**Electron shell:** `cd electron; npm test` runs `node --test test/**/*.test.js`;
`npm run dist:win` builds the NSIS installer.

**Freeze the API** (one-dir bundle at `dist/emb-api/emb-api.exe` + `_internal/`):
```powershell
python -m PyInstaller emb-api.spec --noconfirm
```
Build it from the env that has the runtime deps (`pyAI`), not a bare system
Python. [emb-api.spec](emb-api.spec) carries an `EXCLUDES` list because `python-pptx → PIL`
optionally references IPython and Tk; without it a dev env leaks ~25 MB of
notebook stack into the bundle.

**Stage the Neo4j + JRE homes** that `build-release.ps1` consumes (unpack,
configure for loopback, optionally set the password and load the graph dump):
```powershell
pwsh -File scripts/stage-neo4j.ps1 -Zip <neo4j-community-*.zip> -JreZip <jre.zip> `
     -Password <pw> -Dump .\release\neo4j.dump
```
Neo4j Community downloads live at `https://dist.neo4j.org/neo4j-community-<version>-windows.zip`
(plus `.sha256`). The Deployment Center UI lists **only the newest release**, so
fetch older lines by direct URL rather than assuming they're gone.

**Build the release assets** (frozen API + Neo4j + JRE + dump + corpus, then
checksums into `electron/resources/assets.manifest.json`):
```powershell
pwsh -File electron/scripts/build-release.ps1 -Neo4jHome <dir> -JreHome <dir>
cd electron; npm run dist:win          # bakes the manifest into the installer
pwsh -File scripts/stage-usb.ps1 -Verify
```
Run them in that order — `stage-usb.ps1` fails if the installer carries a
different manifest than `release/`, or if any asset's SHA-256 doesn't match.

**Reset the graph** (drop all Chunk nodes before re-ingesting), in Neo4j Browser
at `http://localhost:7474`:
```cypher
MATCH (c:Chunk) DETACH DELETE c
```
Preserves Directory, File, and entity nodes.

## Contribution Workflow

**Never commit directly to `main`.** Every task — however small — ships through a pull request.

1. **Branch from `main`.** Make sure `main` is current first:
   ```bash
   git checkout main
   git pull
   git checkout -b claude/<short-description>
   ```
   Branch names use the `claude/` prefix plus a short kebab-case description
   (e.g. `claude/graph-ingest-router`, `claude/fix-neo4j-session-leak`).
2. **Test locally** against the native stack. If a test still assumes Docker
   (container hostnames, `docker exec`), refactor it to the native architecture.
3. **Commit to the branch.** Small, focused commits whose messages describe *why*.
4. **Open a pull request** against `main`:
   ```bash
   git push -u origin claude/<short-description>
   gh pr create --base main
   ```
   The PR body states what changed, why, and the exact test commands run with results.
5. **Stop there and report the PR URL.** Do not merge — that is the repo owner's
   call. Do not use `--no-verify` or otherwise bypass hooks.

## Architecture

### Data pipeline (run order matters)

```
pipeline/ingest.py        →  Directory → File → Chunk nodes, stores embeddings
pipeline/load_manifest.py →  reads MANIFEST*.md, sets File.title and links Category/
                             Source/Edition/WhyItMatters/Validated metadata nodes
pipeline/enrich.py        →  reads Chunk nodes, calls the LLM, creates Concept/
                             Organization/LegalReference/Course nodes and
                             MaterialType classification
```

All three stages are idempotent. Ingestion skips files that already have embedded
chunks (`is_file_embedded()`); manifest load is all MERGEs keyed on `File.filepath`;
enrichment skips `c.enriched = true` chunks and already-typed documents.
Ingestion and enrichment need host Ollama reachable at `settings.ollama_base_url`;
the manifest load makes no LLM calls.

Ingestion supports `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, and **excludes
`MANIFEST*.md`** (that's corpus metadata, not content). `File.filepath` is stored
in forward-slash (POSIX) form via `Path.as_posix()` so Windows ingestion, the
`/files` URL space, and the shipped graph dump all agree.

[pipeline/extract.py](pipeline/extract.py) is **not** a standalone pipeline — it is a shared library
called by both `enrich.py` (batch) and `rag.py` (per query, for entity extraction
at query time).

`enrich.py` Pass 2 is thread-pooled (`enrichment_concurrency`, default 4) — Neo4j
writes stay serial on the main thread; only the LLM calls fan out. Real speedup
requires host Ollama to allow that many parallel slots (`OLLAMA_NUM_PARALLEL`)
and the VRAM for their KV caches.

`load_manifest.py` uses **hybrid** resolution: each manifest row matches existing
File nodes by filename; if none exist, a catalog File node is created at the
synthetic path `{data_root}/{category}/{filename}`, so a later real ingestion
merges into the same node. After loading rows it also creates the **curated**
`SUPERSEDES`/`VARIANT_OF` file-to-file edges from the module-level
`SUPERSEDES_EDGES` and `VARIANT_GROUPS` lists (extracted by hand from the manifest
prose, matched by filename — update these lists when documents are superseded or
duplicated).

### Graph schema

```
Directory -[:CONTAINS_DIR]->   Directory
Directory -[:CONTAINS_FILE]->  File           (.filepath (unique), .filename, .title, .extension)
File      -[:HAS_CHUNK]->      Chunk          (.embedding, .text, .sequence, .enriched)
File      -[:IS_TYPE]->        MaterialType
File      -[:REFERENCES]->     Course
File      -[:IN_CATEGORY]->    Category       (manifest: category column)
File      -[:HAS_SOURCE]->     Source         (manifest: source URL)
File      -[:HAS_EDITION]->    Edition        (manifest: edition/date — .value is a free string)
File      -[:EXPLAINS]->       WhyItMatters   (manifest: why-it-matters text)
File      -[:HAS_VALIDATION]-> Validated      (manifest: validated column — yes/size)
File      -[:FROM_TRANCHE]->   Tranche        (derived from manifest H1 title)
File      -[:HAS_ACCESS]->     Access         (.level — login-gated / public, inferred from source URL)
File      -[:SUPERSEDES]->     File           (curated — see load_manifest.py)
File      -[:VARIANT_OF]->     File           (curated: duplicate/variant → canonical copy)
Chunk     -[:MENTIONS]->       Concept | Organization
Chunk     -[:CITES]->          LegalReference
WhyItMatters -[:RELATES_TO]->  Concept
```

The `File` node was formerly `Document`. Category/Source/Edition/WhyItMatters/
Validated nodes come from `load_manifest.py`, not from ingestion or enrichment.

All Cypher lives as module-level string constants in [src/database/schema.py](src/database/schema.py)
(constraints, the `chunk_vector_idx` vector index, and every MERGE/LINK/FETCH).
`setup_constraints(driver)` is called from the FastAPI lifespan, so an empty
database is fine on first boot. The vector features used
(`db.index.vector.queryNodes`, `vector.similarity.cosine`) are Neo4j **core** —
no APOC/GDS plugin, so native Neo4j works with no extra install.

### RAG pipeline ([src/services/rag.py](src/services/rag.py))

Every chat request runs `_retrieve_and_build_messages()`:

1. Embed the question via `generate_embedding()` (Ollama `/api/embeddings`)
2. Vector search: `db.index.vector.queryNodes('chunk_vector_idx', top_k, embedding)`, filtered by `settings.vector_retrieval_min_score`
3. Entity extraction: `extract_entities()` (LLM call via `/api/generate`) pulls concepts, organizations, and legal references from the question
4. Graph traversal: finds chunks linked to those entities, scores them with `vector.similarity.cosine()`, filtered by `settings.graph_retrieval_min_score`
5. Merge: vector results first, graph results appended — deduped by both `chunk_id` and the first 200 chars of text
6. Build `[system] + recent history + [user+context]` and hand to the LLM

Graph traversal failures degrade gracefully to vector-only, logged at WARNING
with the traceback. Streaming (`/chat/stream`) and non-streaming (`/chat/`) share the same
retrieval path. The token generator in `stream_answer()` stores the turn in
session history via a `finally` block, so history survives an early client
disconnect.

**Superseded documents are not filtered from retrieval** — they stay citable for
historical purposes. Both retrieval queries look up any `(:File)-[:SUPERSEDES]->(doc)`
edge and attach `superseded_by` to the source; the context label is annotated
(`SUPERSEDED by … (historical reference)`), the system prompt tells the LLM to
prefer the current version, and the API/UI surface the flag.

**Prompt-injection mitigation:** the user's question is fenced between
`[USER_INPUT_START]` / `[USER_INPUT_END]` and the system prompt instructs the
model to treat everything inside those markers — and all retrieved context — as
data, never instructions. Keep that fencing intact when editing the prompt.

Only `history_injection_turns` recent turns are prepended to the prompt (the full
`max_history_turns` is still retained for `/history` reads) so prompt-eval cost
doesn't grow unbounded on long conversations.

### LLM calls ([src/services/llm.py](src/services/llm.py))

`chat-model` (gemma4) is a reasoning model. Requests set `"think": False` —
left on, it burns the entire `num_predict` budget emitting chain-of-thought into
a separate `thinking` channel and leaves `response` empty. Don't remove that flag.
Entity extraction uses Ollama's `format: json` mode plus a low `num_predict` cap
so the model stops as soon as the object closes.

### Session management ([src/services/session.py](src/services/session.py))

In-memory conversation store keyed by UUID, thread-safe via `threading.Lock`,
capped at `max_history_turns * 2` messages using `collections.deque`. The
singleton `conversation_store` is imported by both `rag.py` and `chat.py`.
State is process-local — it does not survive a reload or restart.

### Resource paths ([src/core/paths.py](src/core/paths.py))

`resource_root()` / `modelfile_path()` / `static_dir()` resolve runtime resources
(the two Modelfiles, the static UI) correctly both from source and inside a
PyInstaller bundle (`sys.frozen` / `sys._MEIPASS`), independent of the current
working directory. **Any new file the app reads at runtime should be resolved
through these**, not via a repo-relative path — otherwise it breaks when frozen.
A frozen build must `--add-data` those resources so they land under `resource_root()`.

### Configuration ([src/core/config.py](src/core/config.py))

All tuneable values live in `Settings` (pydantic-settings, reads `.env`,
case-insensitive, `extra="ignore"` because the shared `.env` carries keys this
model doesn't declare — `NEO4J_AUTH`, `DB_URI`, and leftover compose keys).

`DB_URI` and `NEO4J_AUTH` are **not** in `Settings` — [src/database/connection.py](src/database/connection.py)
reads them from `os.environ` directly.

| Setting | Default | Purpose |
|---|---|---|
| `retrieval_top_k` | 3 | Vector results per query |
| `answer_max_tokens` | 700 | Cap (`num_predict`) on chat answer length — bounds the dominant generation-latency cost on GPU-limited hosts |
| `vector_retrieval_min_score` | 0.75 | Floor for vector chunk inclusion |
| `graph_retrieval_min_score` | 0.78 | Floor for graph chunk inclusion |
| `graph_retrieval_limit` | 2 | Max graph-augmented chunks per query |
| `chunk_max_tokens` | 512 | Ingestion chunk size (~4 chars/token) |
| `chunk_overlap_tokens` | 64 | Overlap between consecutive chunks |
| `max_history_turns` | 10 | Conversation turns retained per session |
| `history_injection_turns` | 4 | Recent turns prepended to the LLM prompt |
| `chat_num_ctx` | 8192 | Context window (KV-cache size) requested for chat-model calls |
| `rate_limit_per_minute` | 20 | Max chat requests per client IP per minute (429 over limit) |
| `entity_extraction_max_tokens` | 256 | `num_predict` cap for the per-query entity-extraction call |
| `enrichment_concurrency` | 4 | Parallel LLM calls in enrich.py Pass 2 (~2.3× on an RTX 4000 Ada) |
| `data_root` | `/app/project_data` | Ingestion root **and** the base for `/files` citation links |
| `ollama_base_url` | `http://localhost:11434` | Host-native Ollama |
| `ollama_startup_retries` / `_delay` / `_request_timeout` / `_pull_timeout` | 5 / 3.0s / 10s / 1800s | Bootstrap retry + timeout budget (pull covers a ~10 GB cold download) |
| `log_dir` | `None` | `LOG_DIR` — set (or running frozen) ⇒ rotating `api.log` files only; unset ⇒ console only. See Logging below |
| `log_level` | `INFO` | Level for all `em_b.*` loggers. `DEBUG` also logs user question text |
| `log_max_bytes` / `log_backup_count` | 10 MB / 5 | `api.log` rotation size and backups kept |
| `timing_log_enabled` | `True` | Master switch for per-stage query timing logs (`em_b.timing` logger) |
| `timing_log_level` | `INFO` | Log level for the timing logger |

> **Leftover container defaults — a real trap.** `settings.data_root` still
> defaults to `/app/project_data`, and `pipeline/load_manifest.py` has a
> `DEFAULT_DATA_ROOT = "/app/project_data"`. Nothing on a Windows host lives
> there. **Always set `DATA_ROOT` in `.env`** (absolute, forward slashes, e.g.
> `C:/Users/seprior/EM_B_Hybrid/project_data`). The value you ingest with must be
> the value you serve with, or `/files` citation links won't resolve. Cleaning up
> those defaults is fair game.

Per-stage timing instrumentation lives in [src/core/timing.py](src/core/timing.py). When enabled,
each chat query emits one `rag stages …` wall-clock line (embed / vector_query /
extract_entities / graph_query) plus one `ollama call=… …` line per Ollama call
carrying the model's internal `load`/`prompt_eval`/`eval` durations — correlated
by a short `sid`. Use these to attribute query latency and to confirm models stay
warm (low `load=` ms) under `OLLAMA_KEEP_ALIVE`.

### Logging ([src/core/logging_config.py](src/core/logging_config.py), [electron/lib/logger.js](electron/lib/logger.js))

Every Python logger is `logging.getLogger("em_b.<area>")` (`em_b.main`, `em_b.rag`,
`em_b.chat`, `em_b.timing`, …). **Modules never attach handlers.** `configure_logging()`
installs the single handler on `em_b`; it runs first in the lifespan and at the top
of each `pipeline/*.py` `__main__` block. Anything new that runs standalone must call
it too, or its INFO records are silently dropped.

One destination, never both:

- **Console** — dev (`dev-up.ps1`, `uvicorn --reload`, `python -m pipeline.*`).
- **Rotating files** — when `LOG_DIR` is set or the app is frozen. `api.log` gets the
  `em_b.*` records **and** uvicorn's loggers, rerouted because `uvicorn.run` installs
  console handlers before the lifespan. Set `LOG_DIR` in dev to test this path.

The Electron shell mirrors this: `electron.log` (shell events, wizard step
transitions, Neo4j and API child stdout/stderr) in `<userData>/logs` when packaged,
the console in dev unless `LOG_DIR` is set. It passes that dir to the API as
`LOG_DIR`, so **one folder holds both files**. That's what a user sends when reporting
a problem. The two files share a line format.

Rules for new code:

- **Log before raising `HTTPException` from a broad `except`**: `logger.exception(...)`.
  The HTTP body reaches the client, not the log.
- **Never swallow silently.** A graceful fallback logs WARNING with `exc_info=True`.
- **Privacy:** user question text only at DEBUG; retrieved chunk text never. INFO
  and above carry ids, filenames, scores, counts, timings, so a default-level log is
  safe to send.
- Tests: `tests/conftest.py` restores logger state after each test. Use
  `caplog.set_level(..., logger="em_b")` to assert on records.

### Hot reload

`scripts/dev-up.ps1` (or `uvicorn --reload`) restarts the app within seconds when
any Python file under `src/` or `pipeline/` is saved. On reload the startup
bootstrap re-runs, but it is idempotent — the warm path is a single `/api/tags` read.

### API surface

- `POST /chat/` — non-streaming chat → `{answer, session_id, sources}`
- `POST /chat/stream` — SSE: `metadata` event (session_id + sources), then `token` events, then `done`
- `GET /chat/sessions/{id}/history` — retrieve conversation history
- `DELETE /chat/sessions/{id}` — clear a session
- `GET /files/{path}` — stream an ingested source file so chat citations are clickable. Unauthenticated (local-only build) but path-traversal-guarded against `data_root`.
- `POST /admin/ingest` — run ingestion (body `{"data_root": "..."}`, defaults to `settings.data_root`)
- `POST /admin/load-manifest` — load MANIFEST*.md metadata (run after ingest; same body)
- `POST /admin/bootstrap-models` — re-provision host Ollama models without restarting; idempotent, 503 if Ollama is down
- `GET /health` — liveness check
- `GET /graph/nodes` — list up to 10 graph nodes
- `GET /graph/nodes/{id}` — get a node by element ID
- `GET /graph/search?q=term` — text search across node properties (up to 20 results)
- `POST /graph/search` — vector similarity search across chunk embeddings

Interactive API docs: `http://localhost:8000/docs`. The static UI is mounted at
`/` **last** in `main.py` so API routes win.

### Desktop shell ([electron/](electron/))

Electron main process + preload + a first-run wizard; supervises the backend and
navigates to `http://127.0.0.1:8000` once `/health` is green. Fully native:
[supervisor.js](electron/supervisor.js) drives [lib/procs.js](electron/lib/procs.js), which spawns bundled Neo4j
(`neo4j console`, `JAVA_HOME` = the bundled JRE) and the frozen `emb-api.exe`,
probes bolt then `/health`, and kills both process trees on quit. Tests use
Node's built-in runner (`node --test`).

First run ([lib/firstrun.js](electron/lib/firstrun.js), step ids mirrored in [wizard/wizard.js](electron/wizard/wizard.js)):
`gpu → ollama → models → neo4j → runtime → data → snapshot → start`. It unpacks
the assets from a USB `assets/` folder ([lib/assets.js](electron/lib/assets.js)) into
`<userData>/{neo4j,jre,api,project_data,snapshot}`, sets the Neo4j password
**before** first init, loads the dump offline ([lib/snapshot.js](electron/lib/snapshot.js)), then starts
the stack. [lib/apibundle.js](electron/lib/apibundle.js) re-unpacks the API bundle when a shipped
manifest is newer than what's installed, so an app update can't leave the new
shell running the old exe. Only `apibundle`, `logger` and `ollamaenv` have unit
tests — `procs`, `supervisor`, `firstrun`, `snapshot` and `archive` are covered
only by an end-to-end first-run test on a real machine.

When launching `electron .` from a VS Code terminal, clear `ELECTRON_RUN_AS_NODE`
first (`Remove-Item Env:ELECTRON_RUN_AS_NODE`). The extension host sets it, which
makes Electron run as plain Node, so `require('electron')` returns a path string and
`app` is undefined.

## Coding Standards

These conventions are enforced across the codebase. Follow them in all new code.

### Python

- **Type hints:** annotate every argument and return type, modern syntax (`list[str]`, `str | None` — not `List[str]`, `Optional[str]`)
- **Dependency management:** install into your conda/venv with plain pip — `python -m pip install -r requirements-dev.txt` (runtime deps plus ruff, pytest, httpx, pyinstaller). Do **not** run `uv pip install` against a conda env; uv treats it as a system Python and refuses unless pointed at it explicitly (`uv pip install --python "$env:CONDA_PREFIX\python.exe" ...`).
- **Formatting & linting:** Ruff, line length 88, `target-version = "py312"`. `ruff format` (Black-compatible) and `ruff check`. Rules `E,F,I,W,UP,B`; isort first-party = `src`, `pipeline`, `tests`. Config in [pyproject.toml](pyproject.toml).
- **Docstrings:** Google-style for all modules, classes, and public functions
- **String formatting:** f-strings exclusively — no `.format()` or `%` — **except in logging calls**, which use lazy `%`-style args: `logger.info("Connected (version %s)", version)`, never `logger.info(f"...")`. The logging module only formats a record that passes the level filter, so per-query DEBUG lines cost nothing when disabled.
- **Resource management:** always use context managers for file I/O and connections
- **No mutable defaults**

### FastAPI

- Use `APIRouter` for all routes — never put endpoints in `main.py`
- `async def` only for genuine async I/O; `def` for synchronous/CPU-bound handlers (all current handlers are sync — the Neo4j driver and `requests` are blocking)
- Startup/teardown via `lifespan` (`@asynccontextmanager`) — never `@app.on_event`
- Database sessions injected per-request via `Depends()` — no global connection objects in handlers
- Always define `response_model` on route decorators
- Use `fastapi.status` constants — never hardcode HTTP integers
- Raise `HTTPException` — never return error dicts

### Pydantic V2

- `model_validate()`, `model_dump()`, `ConfigDict` — never V1 syntax
- Validators: `@field_validator`, `@model_validator`

### Neo4j

- Driver instantiated once in the FastAPI `lifespan`, closed at teardown (`Neo4jConnection` singleton in [src/database/connection.py](src/database/connection.py))
- Session injected per-request via `Depends()` — each router defines its own `get_session()` / `get_db_session()`. **Read-only routers pass `READ_ACCESS`** so the server rejects accidental writes; only `/admin` uses the default `WRITE_ACCESS`.
- **Never** use f-strings or interpolation to build Cypher — always `$param` placeholders. `validate_cypher_query()` in `connection.py` is a heuristic guard, not a substitute.
- Use `session.execute_read()` / `session.execute_write()` — not auto-commit transactions
- Map Neo4j records to Pydantic models before returning from endpoints
- Connect at the env-provided `DB_URI` (`bolt://127.0.0.1:7687`) — never hardcode a host

### Deployment / process model

- Startup order the shell must enforce: Neo4j (native server + bundled JRE) → wait for bolt → API (uvicorn now, frozen exe later) → poll `/health`. Ollama is host-native and only needs to be ensured running.
- All endpoints bind `127.0.0.1` only. (`api_server.py` is a legacy alternate entry point that still binds `0.0.0.0` — don't use it; prefer `scripts/dev-up.ps1`.)
- GPU acceleration comes entirely from the host's native Ollama install. The app has no GPU code of its own.
- **Neo4j version is store-format-locked to `2026.07.01`** (the line the current graph was built on). A different major line can refuse to open the store — see the pitfall list in [docs/DECONTAINERIZE_PLAN.md](docs/DECONTAINERIZE_PLAN.md). Set the Neo4j password **before first init** (`neo4j-admin dbms set-initial-password`); it is baked into the data dir.
- **Shipping the runtimes (open decision):** recommended — freeze the API with PyInstaller (one-dir) and code-sign it; ship native Neo4j + a bundled JRE unpacked. Installer signing is staged but blocked on a UALR certificate.
- All credentials via `.env` / environment — never hardcoded secrets.
