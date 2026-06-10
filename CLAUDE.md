# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **FastAPI** app served by uvicorn, running inside Docker (`em_b_v1-api-1`)
- **Neo4j** graph database — bolt on port 7687, browser on port 7474
- **Ollama** — local LLM inference; `gemma:latest` for chat/entity extraction, `qwen3-embedding:4b` (2560-dim) for embeddings
- **Static web UI** — chat interface served at `/` from `src/static/` (index.html, app.js, style.css)
- All three services are declared in `docker-compose.yml` and must be running for the app to function

## Common Commands

**Start the stack:**
```
docker compose up -d
```

**Tail API logs (hot-reload is active; file saves apply instantly):**
```
docker logs -f em_b_v1-api-1
```

**Trigger ingestion** (after dropping the database or adding new files):
```
curl.exe -s -X POST http://localhost:8000/admin/ingest | python -m json.tool
```

**Run enrichment** (after ingestion completes):
```
docker exec -it em_b_v1-api-1 python -m pipeline.enrich
```

**Run tests** (inside the container):
```
docker exec em_b_v1-api-1 pytest
```

**Run a single test file:**
```
docker exec em_b_v1-api-1 pytest tests/test_rag.py -v
```

**Run tests by marker:**
```
docker exec em_b_v1-api-1 pytest -m unit
```

**Reset the graph** (drop all Chunk nodes before re-ingesting):
```cypher
MATCH (c:Chunk) DETACH DELETE c
```
Run in Neo4j Browser at `http://localhost:7474`. Preserves Directory, Document, and entity nodes.

## Architecture

### Data pipeline (run order matters)

```
pipeline/ingest.py   →  creates Directory → Document → Chunk nodes, stores embeddings
pipeline/enrich.py   →  reads Chunk nodes, calls LLM, creates Concept/Organization/
                         LegalReference/Course nodes and MaterialType classification
```

Ingestion is idempotent — `is_file_embedded()` skips files that already have chunks with stored embeddings. Enrichment is idempotent — already-enriched chunks (`c.enriched = true`) and already-typed documents are skipped. Both pipelines require Ollama to be running.

`pipeline/extract.py` is not a standalone pipeline — it is a shared library called by both `enrich.py` (batch) and `rag.py` (per query, for entity extraction at query time).

### Graph schema

```
Directory -[:CONTAINS_DIR]-> Directory
Directory -[:CONTAINS_FILE]-> Document
Document  -[:HAS_CHUNK]->    Chunk          (chunk has .embedding, .text, .sequence)
Document  -[:IS_TYPE]->      MaterialType
Document  -[:REFERENCES]->   Course
Chunk     -[:MENTIONS]->     Concept | Organization
Chunk     -[:CITES]->        LegalReference
```

All Cypher queries live in `src/database/schema.py` as module-level string constants. Never build Cypher by string interpolation — always use `$param` placeholders.

### RAG pipeline (`src/services/rag.py`)

Every chat request runs `_retrieve_and_build_messages()`:

1. Embed the question via `generate_embedding()` (Ollama `/api/embeddings`)
2. Vector search: `db.index.vector.queryNodes('chunk_vector_idx', top_k, embedding)` — filtered by `settings.vector_retrieval_min_score`
3. Entity extraction: calls `extract_entities()` (LLM call via `/api/generate`) to pull concepts, organizations, legal references from the question text
4. Graph traversal: finds chunks linked to those entities, scores them with `vector.similarity.cosine()`, filtered by `settings.graph_retrieval_min_score`
5. Merge: vector results first, graph results appended — deduped by both `chunk_id` and first 200 chars of text
6. Build message list: `[system] + history + [user+context]` and hand to the LLM

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

### Hot reload

`docker-compose.yml` mounts `./src`, `./pipeline`, `./project_data`, and `./tests` into the container. Uvicorn runs with `--reload`. Saving any Python file under `src/` or `pipeline/` restarts the app within seconds — no container restart needed.

### API surface

- `POST /chat/` — non-streaming chat, returns `{answer, session_id, sources}`
- `POST /chat/stream` — SSE stream: `metadata` event (session_id + sources), then `token` events, then `done`
- `GET /chat/sessions/{id}/history` — retrieve conversation history
- `DELETE /chat/sessions/{id}` — clear a session
- `POST /admin/ingest` — trigger ingestion pipeline on demand (body: `{"data_root": "/app/project_data"}`)
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
- **Dependency management:** `uv` (or pip via uv)
- **Formatting & linting:** Black (line length 88); Ruff/Flake8 for linting
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
- All credentials via `.env` / environment directives — never hardcoded secrets
- Neo4j has a `healthcheck`; the API service uses `depends_on` with `condition: service_healthy` for both Neo4j and Ollama
- Ollama starts via `ollama-startup.sh`, which pulls `gemma:latest` and `qwen3-embedding:4b` then creates custom model variants from `Modelfile` and `Modelfile.embeddings`
- GPU acceleration is declared in `docker-compose.yml` via nvidia device reservations for the Ollama service
