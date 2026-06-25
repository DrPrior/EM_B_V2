# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **FastAPI** app served by uvicorn, running inside Docker (`em_b_v2-api-1`)
- **Neo4j** graph database — bolt on port 7687, browser on port 7474
- **Ollama** — local LLM inference. **Hybrid architecture: Ollama runs natively on the host, NOT in Docker** (so it uses the host GPU — Metal/CUDA/Vulkan — directly). The API container reaches it at `http://host.docker.internal:11434`. The app calls custom Modelfile-built variants, not the base models directly: `chat-model` (FROM `gemma4:12b-it-qat`, `num_ctx 8192`) for chat/entity extraction, `embedding-model` (FROM `qwen3-embedding:4b`, 2560-dim) for embeddings. Variant names are set in `src/core/config.py`. The variants are pulled/built on the host automatically at API startup by `src/services/ollama_bootstrap.py` over the HTTP bridge — see **`docs/HYBRID_SETUP.md`** for the one-time host setup (install Ollama, set `OLLAMA_HOST=0.0.0.0`)
- **Static web UI** — chat interface served at `/` from `src/static/` (index.html, app.js, style.css)
- Only **Neo4j** and the **API** are declared in `docker-compose.yml`; Ollama must be installed and running on the host. All three must be up for the app to function

## Common Commands

**Start the stack** (Ollama must already be running natively on the host — see `docs/HYBRID_SETUP.md`):
```
docker compose up -d
```
On startup the API waits for host Ollama, then pulls base models and builds the
custom variants if missing (fail-fast: it exits if Ollama is unreachable). To
re-provision models without restarting the container:
```
curl.exe -s -X POST http://localhost:8000/admin/bootstrap-models
```

**Tail API logs (hot-reload is active; file saves apply instantly):**
```
docker logs -f em_b_v2-api-1
```

**Trigger ingestion** (after dropping the database or adding new files):
```
curl.exe -s -X POST http://localhost:8000/admin/ingest | python -m json.tool
```

**Load manifest metadata** (after ingestion, before enrichment):
```
docker exec -it em_b_v2-api-1 python -m pipeline.load_manifest
```

**Run enrichment** (after manifest load completes):
```
docker exec -it em_b_v2-api-1 python -m pipeline.enrich
```

**Full rebuild order** (drop graph → ingest → load manifest → enrich):
```
docker exec -it em_b_v2-api-1 python -m pipeline.ingest
docker exec -it em_b_v2-api-1 python -m pipeline.load_manifest
docker exec -it em_b_v2-api-1 python -m pipeline.enrich
```
`load_manifest` must run **after** `ingest` so its filename-based matching finds
the ingested File nodes. Run earlier and manifest rows whose category column
doesn't match an on-disk folder (most of MANIFEST2.md) create duplicate catalog
nodes at synthetic paths.

**Run tests** (inside the container):
```
docker exec em_b_v2-api-1 pytest
```

**Run a single test file:**
```
docker exec em_b_v2-api-1 pytest tests/test_rag.py -v
```

**Run tests by marker:**
```
docker exec em_b_v2-api-1 pytest -m unit
```

**Reset the graph** (drop all Chunk nodes before re-ingesting):
```cypher
MATCH (c:Chunk) DETACH DELETE c
```
Run in Neo4j Browser at `http://localhost:7474`. Preserves Directory, File, and entity nodes.

## Architecture

### Data pipeline (run order matters)

```
pipeline/ingest.py        →  creates Directory → File → Chunk nodes, stores embeddings
pipeline/load_manifest.py  →  reads MANIFEST*.md, sets File.title and links Category/
                              Source/Edition/WhyItMatters/Validated metadata nodes
pipeline/enrich.py         →  reads Chunk nodes, calls LLM, creates Concept/Organization/
                              LegalReference/Course nodes and MaterialType classification
```

Ingestion is idempotent — `is_file_embedded()` skips files that already have chunks with stored embeddings. Manifest load is idempotent — every write is a MERGE, keyed on the File's `filepath`. Enrichment is idempotent — already-enriched chunks (`c.enriched = true`) and already-typed documents are skipped. Ingestion and enrichment require the host-native Ollama to be running and reachable at `host.docker.internal:11434`; the manifest load does not (no LLM calls).

`pipeline/load_manifest.py` uses **hybrid** resolution: each manifest row is matched to existing File nodes by filename; if none exist, a catalog File node is created keyed on the synthetic path `{data_root}/{category}/{filename}`. The synthetic root is `/app/project_data` (the container ingestion root) so a later real ingestion merges into the same node. It must run after `ingest.py` (see "Full rebuild order" above). After loading rows it also creates the **curated** `SUPERSEDES`/`VARIANT_OF` file-to-file edges from `SUPERSEDES_EDGES` and `VARIANT_GROUPS` (extracted by hand from the manifest prose, matched by filename — update these lists when documents are superseded or duplicated).

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

All Cypher queries live in `src/database/schema.py` as module-level string constants. Never build Cypher by string interpolation — always use `$param` placeholders.

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

All tuneable values are in `Settings` (pydantic-settings, reads from `.env`):

| Setting | Default | Purpose |
|---|---|---|
| `retrieval_top_k` | 5 | Vector results per query |
| `vector_retrieval_min_score` | 0.75 | Floor for vector chunk inclusion |
| `graph_retrieval_min_score` | 0.78 | Floor for graph chunk inclusion |
| `graph_retrieval_limit` | 3 | Max graph-augmented chunks per query |
| `chunk_max_tokens` | 512 | Ingestion chunk size (~4 chars/token) |
| `chunk_overlap_tokens` | 64 | Overlap between consecutive chunks |
| `max_history_turns` | 10 | Conversation turns retained per session |
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

`docker-compose.yml` mounts `./src`, `./pipeline`, `./project_data`, `./tests`, and the two Modelfiles into the container. Uvicorn runs with `--reload`. Saving any Python file under `src/` or `pipeline/` restarts the app within seconds — no container restart needed. (On reload the startup bootstrap re-runs but is idempotent — the warm path is a single `/api/tags` read.)

### API surface

- `POST /chat/` — non-streaming chat, returns `{answer, session_id, sources}`
- `POST /chat/stream` — SSE stream: `metadata` event (session_id + sources), then `token` events, then `done`
- `GET /chat/sessions/{id}/history` — retrieve conversation history
- `DELETE /chat/sessions/{id}` — clear a session
- `POST /admin/ingest` — trigger ingestion pipeline on demand (body: `{"data_root": "/app/project_data"}`)
- `POST /admin/load-manifest` — load MANIFEST*.md metadata into the graph (run after ingest; body: `{"data_root": "/app/project_data"}`)
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
- **Dependency management:** `uv` inside the Docker image (the base image ships with it). For **local development**, install into your conda env with plain pip — `python -m pip install -r requirements-dev.txt`. Don't run `uv pip install` against a conda env; uv treats it as a system Python and refuses unless pointed at it explicitly (`uv pip install --python "$env:CONDA_PREFIX\python.exe" ...`).
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

### Docker

- Base image: Astral uv Python "slim" (`astral/uv:python3.12-bookworm-slim`) — avoid Alpine
- FastAPI connects to Neo4j at `bolt://neo4j:7687` — never `localhost`
- FastAPI connects to Ollama at `http://host.docker.internal:11434` (the host-native daemon) — set via `OLLAMA_BASE_URL`. The `api` service declares `extra_hosts: ["host.docker.internal:host-gateway"]` for Linux portability
- All credentials via `.env` / environment directives — never hardcoded secrets
- Neo4j has a `healthcheck`; the API service uses `depends_on` with `condition: service_healthy` for Neo4j only (Ollama is host-native, outside Docker's `depends_on` — the app's startup bootstrap waits for it instead)
- The custom variants are built on the host at API startup by `src/services/ollama_bootstrap.py`: it waits for host Ollama, pulls `gemma4:12b-it-qat` / `qwen3-embedding:4b`, then creates `chat-model` from `Modelfile` and `embedding-model` from `Modelfile.embeddings` over the HTTP API (idempotent — skips models already present)
- GPU acceleration comes from the **host's** native Ollama install (Metal/CUDA/Vulkan), not from Docker device reservations. See `docs/HYBRID_SETUP.md`
