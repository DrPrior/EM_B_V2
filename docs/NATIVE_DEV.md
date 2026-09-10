# Native dev stack (no Docker)

Workstream B of [`DECONTAINERIZE_PLAN.md`](DECONTAINERIZE_PLAN.md): run the whole
app as native host processes — **no container runtime**. Three pieces:

```
Neo4j (native, bolt 127.0.0.1:7687)  +  Ollama (native, 127.0.0.1:11434)  +  API (uvicorn)
```

> **Status:** the app code is native-safe (paths normalized, endpoints on
> localhost). What is *not* yet automated: installing native Neo4j (below is a
> manual runbook) and packaging the API (that's Workstream C/D). This is the
> developer path; end-user desktop packaging comes later.

## 1. Python environment

Install deps into your active conda/venv with plain pip (not `uv` against a
conda env — see CLAUDE.md):

```powershell
python -m pip install -r requirements-dev.txt
```

## 2. Ollama (host-native)

Already covered by [`HYBRID_SETUP.md`](HYBRID_SETUP.md) §1. **Difference for
native:** you do **not** need `OLLAMA_HOST=0.0.0.0` — the API now talks to Ollama
over `127.0.0.1`, so Ollama can stay on its default loopback bind. Keep the
warmth/perf vars (`OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_MAX_LOADED_MODELS=2`, etc.).
The API builds the `chat-model` / `embedding-model` variants on startup.

## 3. Neo4j (native)

Install a native Neo4j server. **Recommended: Neo4j Community 2026.04.0** — the
same line the shipped `neo4j.dump` was exported from, so a native install can
load that dump later without a store-format mismatch (the version lock in
`DECONTAINERIZE_PLAN.md` §C). Neo4j needs a **JRE (17/21)**; either use a
distribution that bundles one or install Java separately.

Options: the Community **tarball/zip** (unpack, no admin — closest to what the
desktop app will bundle) or **Neo4j Desktop** (GUI, easier for dev).

Set the password to match `NEO4J_AUTH` in your `.env` **before first start**
(Neo4j bakes the password into its data dir on first init):

```powershell
# from the Neo4j install dir, before the first start:
bin\neo4j-admin dbms set-initial-password <the-password-from-NEO4J_AUTH>
bin\neo4j console      # or run it as a service / via Neo4j Desktop
```

The API creates the vector index + constraints itself on startup
(`setup_constraints` in the lifespan), so an empty database is fine — you just
need Neo4j listening on `bolt://127.0.0.1:7687`.

## 4. Configure `.env`

```powershell
Copy-Item .env.example .env
```

Edit `.env`: set `NEO4J_AUTH=neo4j/<your-password>` (same password as step 3),
keep `DB_URI=bolt://127.0.0.1:7687`, and set `DATA_ROOT` to your corpus path
**with forward slashes**, e.g. `DATA_ROOT=C:/Users/seprior/EM_B_Hybrid/project_data`.

## 5. Populate the graph (fresh ingest)

With Neo4j + Ollama running and `.env` loaded into the process (the launcher does
this, or set them manually), run the pipeline in your venv:

```powershell
python -m pipeline.ingest
python -m pipeline.load_manifest
python -m pipeline.enrich
```

`File.filepath` is stored forward-slashed and keyed to your `DATA_ROOT`, so
citation `/files/...` links resolve to your local corpus.

> **Why not just load the shipped `neo4j.dump`?** Its `File.filepath` values are
> keyed to the container path `/app/project_data`, which doesn't exist on a
> Windows host — citation links wouldn't resolve. Re-keying/serving the shipped
> dump natively is a Workstream C task. For dev, a fresh ingest is self-consistent.

## 6. Run the API

```powershell
scripts/dev-up.ps1
```

This loads `.env` into the environment, checks Ollama + Neo4j are reachable, and
starts `uvicorn src.main:app --reload`. Open <http://localhost:8000>.

Tests run natively now (no `docker exec`): `pytest`, or `pytest -m unit`.
