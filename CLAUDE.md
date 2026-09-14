# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ## ⚠️ Decontainerization in progress — read this first
>
> **Docker is being removed.** The organization (UALR) no longer permits Docker,
> so Neo4j and the FastAPI API are moving from containers to **native host
> processes**. Ollama was already host-native and does not change. The target is
> **no container runtime at all** — every service on `127.0.0.1`.
>
> - **Canonical plan + pitfalls:** [`docs/DECONTAINERIZE_PLAN.md`](docs/DECONTAINERIZE_PLAN.md). Read it before doing migration work.
> - **Current reality:** no refactor code has landed yet (branch `Decontainerize`). The Docker stack below still runs the app today. Sections marked **TARGET** describe the native end state; **LEGACY (current)** blocks are what actually works right now.
> - **Do not add new Docker coupling.** New work should assume the native target (localhost endpoints, no `host.docker.internal`, no compose).

## Stack

**TARGET (native):**
- **FastAPI** app served by uvicorn as a **native process** (frozen exe or a venv) on `127.0.0.1:8000`
- **Neo4j** graph database — **native server** (bundled JRE), bolt on `127.0.0.1:7687`, browser on `127.0.0.1:7474`
- **Ollama** — local LLM inference, **native on the host** (uses the host GPU — Metal/CUDA/Vulkan — directly), on `127.0.0.1:11434`. Because the API is also native, it reaches Ollama over plain `localhost` (no `host.docker.internal`, no `OLLAMA_HOST=0.0.0.0`). The app calls custom Modelfile-built variants, not the base models directly: `chat-model` (FROM `gemma4:12b-it-qat`, `num_ctx 8192`) for chat/entity extraction, `embedding-model` (FROM `embeddinggemma:latest`, 768-dim) for embeddings. Variant names are set in `src/core/config.py`. The variants are pulled/built on the host automatically at API startup by `src/services/ollama_bootstrap.py` over HTTP.
- **Static web UI** — chat interface served at `/` from `src/static/` (index.html, app.js, style.css)
- Neo4j, the API, and Ollama must all be up for the app to function. On the desktop app, the Electron shell supervises the native Neo4j + API processes and ensures Ollama is running.

**LEGACY (current):** FastAPI + Neo4j run in Docker (`docker-compose.yml`); the API container reaches host Ollama at `http://host.docker.internal:11434`. This is what runs until the migration lands.

## Common Commands

> **TARGET (native) commands.** These assume the native dev setup described in
> [`docs/DECONTAINERIZE_PLAN.md`](docs/DECONTAINERIZE_PLAN.md) → Workstream B
> (native Neo4j running, deps installed in your conda/venv). The native launch
> script (`scripts/dev-up.ps1`) does **not exist yet** — until it does, use the
> LEGACY block below.

**Start the API** (Neo4j + Ollama already running on the host):
```
uvicorn src.main:app --reload
```
On startup the API verifies Neo4j, waits for Ollama, then pulls base models and builds the custom variants if missing (fail-fast: it exits if Ollama is unreachable). Re-provision models without restarting:
```
curl.exe -s -X POST http://localhost:8000/admin/bootstrap-models
```

**Trigger ingestion** (after dropping the database or adding new files):
```
curl.exe -s -X POST http://localhost:8000/admin/ingest | python -m json.tool
```

**Full rebuild order** (drop graph → ingest → load manifest → enrich), run in your venv:
```
python -m pipeline.ingest
python -m pipeline.load_manifest
python -m pipeline.enrich
```
`load_manifest` must run **after** `ingest` so its filename-based matching finds
the ingested File nodes. Run earlier and manifest rows whose category column
doesn't match an on-disk folder (most of MANIFEST2.md) create duplicate catalog
nodes at synthetic paths.

**Run tests** (in the venv): `pytest` — single file: `pytest tests/test_rag.py -v` — by marker: `pytest -m unit`

**Reset the graph** (drop all Chunk nodes before re-ingesting):
```cypher
MATCH (c:Chunk) DETACH DELETE c
```
Run in Neo4j Browser at `http://localhost:7474`. Preserves Directory, File, and entity nodes.

<details>
<summary><strong>LEGACY (current) Docker commands — still the working path until the refactor lands</strong></summary>

```
docker compose up -d                                         # start the stack (Ollama must be native)
docker logs -f em_b_v2-api-1                                 # tail API logs (hot-reload active)
docker exec -it em_b_v2-api-1 python -m pipeline.ingest      # pipeline steps run inside the container
docker exec -it em_b_v2-api-1 python -m pipeline.load_manifest
docker exec -it em_b_v2-api-1 python -m pipeline.enrich
docker exec em_b_v2-api-1 pytest                             # tests inside the container
```
</details>

## Contribution Workflow

**Never commit directly to `main`.** Every task — however small — ships through a pull request. For each task, in this order:

1. **Branch from `main`.** Make sure `main` is current first, then cut the branch:

   ```bash
   git checkout main
   git pull
   git checkout -b claude/<short-description>
   ```

   Branch names use the `claude/` prefix plus a short kebab-case description of the task (e.g. `claude/graph-ingest-router`, `claude/fix-neo4j-session-leak`).
2. **Test in local environment** App is being refactored to run directly on local machine. If necessary refactor the relavent tests to work with this new arichtecture.

3. **Commit to the branch.** Small, focused commits with messages describing *why* the change was made, not just what changed.

4. **Open a pull request** against `main`:

   ```bash
   git push -u origin claude/<short-description>
   gh pr create --base main
   ```

   The PR body states what changed, why, and the exact test commands that were run along with their results.

5. **Stop there and report the PR URL.** Do not merge — review and merge are the repo owner's call. Do not use `--no-verify` or otherwise bypass hooks.

## Architecture

### Data pipeline (run order matters)

```
pipeline/ingest.py        →  creates Directory → File → Chunk nodes, stores embeddings
pipeline/load_manifest.py  →  reads MANIFEST*.md, sets File.title and links Category/
                              Source/Edition/WhyItMatters/Validated metadata nodes
pipeline/enrich.py         →  reads Chunk nodes, calls LLM, creates Concept/Organization/
                              LegalReference/Course nodes and MaterialType classification
```

Ingestion is idempotent — `is_file_embedded()` skips files that already have chunks with stored embeddings. Manifest load is idempotent — every write is a MERGE, keyed on the File's `filepath`. Enrichment is idempotent — already-enriched chunks (`c.enriched = true`) and already-typed documents are skipped. Ingestion and enrichment require host-native Ollama to be running and reachable at the configured `ollama_base_url` (`http://localhost:11434` natively; `host.docker.internal:11434` under the legacy Docker stack); the manifest load does not (no LLM calls).

`pipeline/load_manifest.py` uses **hybrid** resolution: each manifest row is matched to existing File nodes by filename; if none exist, a catalog File node is created keyed on the synthetic path `{data_root}/{category}/{filename}`. The synthetic root is the configured `data_root` (the ingestion root — `/app/project_data` under Docker today, a host path once native) so a later real ingestion merges into the same node. It must run after `ingest.py` (see "Full rebuild order" above). After loading rows it also creates the **curated** `SUPERSEDES`/`VARIANT_OF` file-to-file edges from `SUPERSEDES_EDGES` and `VARIANT_GROUPS` (extracted by hand from the manifest prose, matched by filename — update these lists when documents are superseded or duplicated).

`pipeline/extract.py` is not a standalone pipeline — it is a shared library called by both `enrich.py` (batch) and `rag.py` (per query, for entity extraction at query time).

### Graph schema

```
Directory -[:CONTAINS_DIR]->   Directory
Directory -[:CONTAINS_FILE]->  File           (file has .filepath (unique), .filename, .title, .extension)
File      -[:HAS_CHUNK]->      Chunk          (chunk has .embedding, .text, .sequence)
File      -[:IS_TYPE]->        MaterialType
File      -[:REFERENCES]->     Course
File      -[:IN_CATEGORY]->    Category       (manifest: category column)
File      -[:HAS_SOURCE]->     Source         (manifest: source URL)
File      -[:HAS_EDITION]->    Edition        (manifest: edition/date — .value is a free string)
File      -[:EXPLAINS]->       WhyItMatters   (manifest: why-it-matters text)
File      -[:HAS_VALIDATION]-> Validated      (manifest: validated column — yes/size)
File      -[:FROM_TRANCHE]->   Tranche        (manifest: derived from H1 title — Round 2 / Tranche 1)
File      -[:HAS_ACCESS]->     Access         (.level — login-gated / public, inferred from source URL)
File      -[:SUPERSEDES]->     File           (curated: newer edition supersedes older — see load_manifest.py)
File      -[:VARIANT_OF]->     File           (curated: duplicate/variant points to the canonical copy)
Chunk     -[:MENTIONS]->       Concept | Organization
Chunk     -[:CITES]->          LegalReference
WhyItMatters -[:RELATES_TO]->  Concept
```

The `File` node was formerly `Document`. The `Category`/`Source`/`Edition`/`WhyItMatters`/`Validated` nodes and their relationships are populated by `pipeline/load_manifest.py`, not by ingestion or enrichment.

All Cypher queries live in `src/database/schema.py` as module-level string constants. Never build Cypher by string interpolation — always use `$param` placeholders. The vector features used (`db.index.vector.queryNodes`, `vector.similarity.cosine`) are Neo4j **core** — no APOC/GDS plugin is required, so native Neo4j works with no extra install.

### RAG pipeline (`src/services/rag.py`)

Every chat request runs `_retrieve_and_build_messages()`:

1. Embed the question via `generate_embedding()` (Ollama `/api/embeddings`)
2. Vector search: `db.index.vector.queryNodes('chunk_vector_idx', top_k, embedding)` — filtered by `settings.vector_retrieval_min_score`
3. Entity extraction: calls `extract_entities()` (LLM call via `/api/generate`) to pull concepts, organizations, legal references from the question text
4. Graph traversal: finds chunks linked to those entities, scores them with `vector.similarity.cosine()`, filtered by `settings.graph_retrieval_min_score`
5. Merge: vector results first, graph results appended — deduped by both `chunk_id` and first 200 chars of text
6. Build message list: `[system] + history + [user+context]` and hand to the LLM

Superseded documents are **not** filtered from retrieval — they remain citable for historical purposes. Instead, the retrieval queries look up any `(:File)-[:SUPERSEDES]->(doc)` edge and attach a `superseded_by` field to each source; the context label is annotated (`SUPERSEDED by … (historical reference)`), the system prompt tells the LLM to prefer the current version, and the API/UI surface the flag.

Graph traversal failures degrade gracefully to vector-only results (exception is swallowed). Streaming (`/chat/stream`) and non-streaming (`/chat/`) share the same retrieval path. The token generator in `stream_answer()` stores the turn in session history via a `finally` block so history is preserved even on early client disconnect.

### Session management (`src/services/session.py`)

In-memory conversation store keyed by UUID. Thread-safe via `threading.Lock`. History is capped at `max_history_turns * 2` messages using `collections.deque`. The singleton `conversation_store` is imported by both `rag.py` and `chat.py`.

### Configuration (`src/core/config.py`)

All tuneable values are in `Settings` (pydantic-settings, reads from `.env`). Connection settings relevant to decontainerization: `ollama_base_url` (defaults to `http://localhost:11434` — the native value; the legacy Docker stack overrides it to `host.docker.internal`), and `data_root` (defaults to `/app/project_data` — the container path; set to a host path when running native). `DB_URI` is read from the environment by `src/database/connection.py` (`bolt://neo4j:7687` under Docker; `bolt://127.0.0.1:7687` native).

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
| `history_injection_turns` | 4 | Recent turns prepended to the LLM prompt — caps prompt (and prompt-eval) growth as a conversation runs long |
| `chat_num_ctx` | 8192 | Context window (KV-cache size) requested for chat-model calls |
| `rate_limit_per_minute` | 20 | Max chat requests per client IP per minute (429 over limit) |
| `entity_extraction_max_tokens` | 256 | Token cap (`num_predict`) for the per-query entity-extraction LLM call |
| `timing_log_enabled` | `True` | Master switch for per-stage query timing logs (`em_b.timing` logger) |
| `timing_log_level` | `INFO` | Log level for the timing logger |

Per-stage timing instrumentation lives in `src/core/timing.py`. When enabled,
each chat query emits one `rag stages …` wall-clock line (embed / vector_query /
extract_entities / graph_query) plus one `ollama call=… …` line per Ollama call
carrying the model's internal `load`/`prompt_eval`/`eval` durations — all
correlated by a short `sid`. Use these to attribute query latency and to confirm
models stay warm (low `load=` ms) under `OLLAMA_KEEP_ALIVE`.

### Hot reload

Native: run `uvicorn src.main:app --reload` from the repo — saving any Python file under `src/` or `pipeline/` restarts the app within seconds. (On reload the startup bootstrap re-runs but is idempotent — the warm path is a single `/api/tags` read.) **LEGACY:** `docker-compose.yml` mounted `./src`, `./pipeline`, `./project_data`, `./tests`, and the Modelfiles into the container and ran uvicorn with `--reload` for the same effect.

### API surface

- `POST /chat/` — non-streaming chat, returns `{answer, session_id, sources}`
- `POST /chat/stream` — SSE stream: `metadata` event (session_id + sources), then `token` events, then `done`
- `GET /chat/sessions/{id}/history` — retrieve conversation history
- `DELETE /chat/sessions/{id}` — clear a session
- `POST /admin/ingest` — trigger ingestion pipeline on demand (body: `{"data_root": "..."}`)
- `POST /admin/load-manifest` — load MANIFEST*.md metadata into the graph (run after ingest; body: `{"data_root": "..."}`)
- `POST /admin/bootstrap-models` — re-provision the host-native Ollama models (pull base + build custom variants) without restarting the API; idempotent
- `GET /health` — liveness check
- `GET /graph/nodes` — list up to 10 graph nodes
- `GET /graph/nodes/{id}` — get a node by element ID
- `GET /graph/search?q=term` — text search across node properties (up to 20 results)
- `POST /graph/search` — vector similarity search across chunk embeddings

Interactive API docs: `http://localhost:8000/docs`

## Coding Standards

These conventions are enforced across the codebase. Follow them in all new code.

### Python

- **Type hints:** Always annotate function arguments and return types using modern Python syntax (`list[str]` not `List[str]`)
- **Dependency management:** For **local/native development**, install into your conda env with plain pip — `python -m pip install -r requirements-dev.txt`. Don't run `uv pip install` against a conda env; uv treats it as a system Python and refuses unless pointed at it explicitly (`uv pip install --python "$env:CONDA_PREFIX\python.exe" ...`). (The legacy Docker image used `uv` internally; that goes away with the image.)
- **Formatting & linting:** Ruff (line length 88) — `ruff format` for formatting (Black-compatible) and `ruff check` for linting. Config lives in `pyproject.toml`; dev tooling is pinned in `requirements-dev.txt`.
- **Docstrings:** Google-style for all classes, modules, and public functions
- **String formatting:** f-strings exclusively — no `.format()` or `%`
- **Resource management:** Always use context managers (`with`) for file I/O or connections
- **No mutable defaults:** Never use lists or dicts as default function arguments

### FastAPI

- Use `APIRouter` for all routes — never put endpoints directly in `main.py`
- `async def` only for genuine async I/O; use `def` for synchronous/CPU-bound handlers
- Startup/teardown via `lifespan` (`@asynccontextmanager`) — never `@app.on_event`
- Database sessions injected per-request via `Depends()` — no global connection objects in route handlers
- Always define `response_model` on route decorators
- Use `fastapi.status` constants — never hardcode HTTP integers
- Raise `HTTPException` — never return error dicts

### Pydantic V2

- Use `model_validate()`, `model_dump()`, `ConfigDict` — never V1 syntax
- Validators: `@field_validator`, `@model_validator`

### Neo4j

- Driver instantiated once in the FastAPI `lifespan`, closed during teardown (`Neo4jConnection` singleton in `src/database/connection.py`)
- Session injected per-request via `Depends()` — each router module defines its own `get_session()` / `get_db_session()` dependency
- **Never** use f-strings or string interpolation to build Cypher — always `$param` placeholders
- Use `session.execute_read()` / `session.execute_write()` — not auto-commit transactions
- Map Neo4j records to Pydantic models before returning from endpoints
- Connect at the env-provided `DB_URI` — `bolt://127.0.0.1:7687` native, `bolt://neo4j:7687` under the legacy Docker stack. Never hardcode a host.

### Deployment / process model (native TARGET)

- The app runs as native processes, supervised by the Electron shell on the desktop: Neo4j (native server + bundled JRE) → wait for bolt → API (uvicorn, frozen exe or venv) → poll `/health`. Ollama is host-native and ensured-running by the shell.
- All endpoints bind `127.0.0.1` only. The API reaches Ollama over `http://localhost:11434` — no `host.docker.internal`, and Ollama does **not** need `OLLAMA_HOST=0.0.0.0` (that requirement existed only because the API was containerized).
- The custom variants are built at API startup by `src/services/ollama_bootstrap.py`: it waits for host Ollama, pulls `gemma4:12b-it-qat` / `embeddinggemma:latest`, then creates `chat-model` from `Modelfile` and `embedding-model` from `Modelfile.embeddings` over the HTTP API (idempotent — skips models already present).
- GPU acceleration comes from the host's native Ollama install (Metal/CUDA/Vulkan). The app has no GPU code of its own.
- **Shipping the runtimes (OPEN decision):** recommended — freeze the API with PyInstaller (one-dir) and code-sign it; ship native Neo4j + a bundled JRE unpacked. See [`docs/DECONTAINERIZE_PLAN.md`](docs/DECONTAINERIZE_PLAN.md) for alternatives and the full pitfall list (Neo4j store-format version lock to 2026.07.01, set Neo4j password before first init, IT unsigned-installer block, process supervision you now own). Note `unstructured` is unused and being dropped, so it is no longer a freeze risk.
- All credentials via `.env` / environment — never hardcoded secrets.

> **LEGACY Docker notes (being removed):** base image `astral/uv:python3.12-bookworm-slim`; API→Neo4j at `bolt://neo4j:7687`; API→Ollama at `host.docker.internal:11434` with `extra_hosts: ["host.docker.internal:host-gateway"]`; Neo4j `healthcheck` + `depends_on: condition: service_healthy`. See `docker-compose.yml`, `docker-compose.desktop.yml`, `Dockerfile`, `Dockerfile.prod` — all slated for removal per the plan.
