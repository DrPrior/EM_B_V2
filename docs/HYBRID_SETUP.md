# Host-native Ollama — setup, GPU verification, graph sharing

> **The "hybrid" architecture this file used to describe is gone.** Neo4j and the
> API no longer run in Docker; every service is a native process on `127.0.0.1`.
> See [`DECONTAINERIZE_PLAN.md`](DECONTAINERIZE_PLAN.md) for the architecture and
> [`NATIVE_DEV.md`](NATIVE_DEV.md) for the dev runbook (installing native Neo4j,
> `.env`, `scripts/dev-up.ps1`).
>
> What remains here is the part that was never containerized: **Ollama on the
> host**, plus GPU verification, graph sharing, and the startup tuning knobs.

Ollama runs natively so it can use the host GPU directly (Apple **Metal**, NVIDIA
**CUDA**, or Intel Arc **Vulkan**) with no passthrough loss. Because the API is
now native too, it reaches Ollama over plain `http://localhost:11434` — **Ollama
keeps its default loopback bind**; nothing needs to be exposed.

The API **provisions its models automatically on startup** — you do not need to
pull models or build the custom variants by hand.

---

## One-time host setup

### 1. Install Ollama natively

- **macOS (Apple Silicon):** install the [Ollama macOS app](https://ollama.com/download)
  or `brew install ollama`. Metal acceleration works out of the box.
- **Windows (NVIDIA or Intel Arc):** run the official `OllamaSetup.exe` from
  <https://ollama.com/download>. NVIDIA uses CUDA automatically; modern Intel Arc
  GPUs are used via Vulkan.

### 2. Set the recommended host environment variables

> 🖥️ **Desktop-app users can skip this section.** The wizard sets and persists
> these variables automatically (plus `OLLAMA_IGPU_ENABLE=1` on Intel-integrated-
> GPU hosts; on macOS it also installs a login agent so they survive a reboot) and
> restarts Ollama to apply them — [`electron/lib/ollamaenv.js`](../electron/lib/ollamaenv.js).
> It also **removes** a stale user-scope `OLLAMA_HOST=0.0.0.0` left behind by a
> Docker-era build. The steps below are for the **manual / developer path**.

These keep both models resident in memory and tune inference throughput. They are
backend-agnostic — they help NVIDIA, Metal, and Intel hosts alike. See
[the Performance explainer](explainer/gpu-performance.html) for the measurements
behind them.

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_KEEP_ALIVE` | `-1` | Keep models loaded indefinitely so there is no reload lag between the embedding and chat steps of each query. |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Keep the 12B chat model and the embedding model co-resident; prevents Ollama from unloading one to make room for the other ("model thrashing"). |
| `OLLAMA_FLASH_ATTENTION` | `1` | Fused attention over the KV cache. Cuts the time to process a large retrieval prompt **and** the per-token slowdown a long context causes — the two costs that dominate query latency. CUDA/Metal support it fully; on a Vulkan build without it, it is silently ignored (safe to set anywhere). |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Store the KV cache at 8-bit, roughly halving its memory (requires `OLLAMA_FLASH_ATTENTION=1`). Frees headroom on a shared-VRAM iGPU so the two co-resident models aren't squeezed; negligible quality impact. |
| `OLLAMA_NUM_PARALLEL` | `1` | One inference slot instead of an auto-chosen 2–4. Each slot reserves its own KV cache; on a shared-VRAM host that reservation is what evicts a co-resident model and causes 17–25 s mid-session reload spikes. A single-user app never needs more than one slot. **Raise it only if you want parallel enrichment** (`enrichment_concurrency` in `pipeline/enrich.py` fans out LLM calls, which needs the slots and the VRAM for their KV caches). |
| `OLLAMA_IGPU_ENABLE` | `1` | **Intel integrated GPUs only** (Arc iGPU such as the Lunar Lake **Arc 140V**, or Iris Xe). Ollama enumerates the iGPU via Vulkan but then *drops* it by default (`server.log`: `dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1`) and silently falls back to CPU. This flips offload back on. **Do not set it on NVIDIA or Apple hosts.** Pair with `OLLAMA_VULKAN=1` if your Ollama build doesn't enable Vulkan by default. |

> ⚠️ **Do not set `OLLAMA_HOST=0.0.0.0`.** It was required only because the API
> ran in a container and reached Ollama across the Docker bridge. Setting it now
> puts Ollama's **unauthenticated** API on every network interface for no benefit.
> If a previous setup persisted it, remove it (see *Reverting the Docker-era
> network exposure* below).

> ℹ️ **Persistence:** Ollama re-reads these variables **every time the daemon
> starts**, so what matters is whether they're stored persistently in the OS. Set
> them with the methods below (not with a per-shell `$env:` / `export`, which only
> lasts for that session). The *models* themselves are never persistent — after an
> Ollama restart or reboot, VRAM starts empty and models reload on the first query,
> then stay resident because `OLLAMA_KEEP_ALIVE=-1` is still in effect.

**Windows (persists permanently):**

1. Search the Start Menu for **"Edit the system environment variables"**.
2. Add the variables from the table above (or use `setx OLLAMA_KEEP_ALIVE -1`, etc.).
3. Quit Ollama from the system tray and relaunch it.

Set once — every future restart and reboot picks them up automatically.

**macOS:**

```bash
launchctl setenv OLLAMA_KEEP_ALIVE "-1"
launchctl setenv OLLAMA_MAX_LOADED_MODELS "2"
launchctl setenv OLLAMA_FLASH_ATTENTION "1"
launchctl setenv OLLAMA_KV_CACHE_TYPE "q8_0"
launchctl setenv OLLAMA_NUM_PARALLEL "1"
```

Then fully quit and relaunch the Ollama app.

> ⚠️ **macOS gotcha (manual path only):** `launchctl setenv` survives an Ollama
> app restart but is **lost on reboot / logout** — you'd have to re-run it. For
> true persistence, add a **LaunchAgent** that sets them at login. (The desktop
> app does exactly this automatically — see
> [`electron/lib/ollamaenv.js`](../electron/lib/ollamaenv.js).) Create
> `~/Library/LaunchAgents/com.ollama.env.plist`:
>
> ```xml
> <?xml version="1.0" encoding="UTF-8"?>
> <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
>   "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
> <plist version="1.0">
> <dict>
>   <key>Label</key><string>com.ollama.env</string>
>   <key>ProgramArguments</key>
>   <array>
>     <string>sh</string><string>-c</string>
>     <string>launchctl setenv OLLAMA_KEEP_ALIVE -1; launchctl setenv OLLAMA_MAX_LOADED_MODELS 2; launchctl setenv OLLAMA_FLASH_ATTENTION 1; launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0; launchctl setenv OLLAMA_NUM_PARALLEL 1</string>
>   </array>
>   <key>RunAtLoad</key><true/>
> </dict>
> </plist>
> ```
>
> Then `launchctl load ~/Library/LaunchAgents/com.ollama.env.plist` (it also runs
> automatically at each login). Relaunch the Ollama app afterward.

### 3. Verify Ollama is reachable

```bash
curl http://localhost:11434/api/version
```

You should get a JSON version string. If it hangs or refuses, Ollama isn't running.

---

## Start the stack

See [`NATIVE_DEV.md`](NATIVE_DEV.md) — in short: start native Neo4j, then
`scripts/dev-up.ps1`. On startup the API will:

1. Wait for the host Ollama daemon (retries `ollama_startup_retries` times; if it
   never answers the API **exits** with a clear message — start Ollama and bring
   it back up).
2. Pull the base models (`gemma4:12b-it-qat`, `embeddinggemma:latest`) if missing —
   the first run downloads ~10 GB, so be patient.
3. Build the custom `chat-model` / `embedding-model` variants from
   [`Modelfile`](../Modelfile) and [`Modelfile.embeddings`](../Modelfile.embeddings)
   if missing.

Confirm the variants landed on the host:

```bash
ollama list   # should list chat-model and embedding-model
```

### Re-provisioning without a restart

If you change a Modelfile or need to rebuild a variant, re-run the bootstrap
without restarting the API:

```powershell
curl.exe -s -X POST http://localhost:8000/admin/bootstrap-models
```

---

## Verify Arc / GPU acceleration

This app has **no GPU code of its own** — all GPU use happens inside host-native
Ollama, which serves the `chat-model` / `embedding-model` variants and offloads
them to the host GPU (Apple Metal, NVIDIA CUDA, or **Intel Arc via Vulkan**).
There is nothing to emulate: "testing on an Intel Arc GPU" means confirming that
Ollama loaded the models into GPU VRAM on the Arc machine instead of silently
falling back to CPU. (Intel's **SDE** emulates *CPU* instruction sets, not GPUs,
and does not apply here.)

Run the bundled check **on the machine with the Arc GPU**, with Ollama running:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-arc-gpu.ps1
```

It confirms the daemon is reachable, scans `server.log` for the backend Ollama
selected (`vulkan` / `intel` / `no compatible GPUs`), warms `chat-model` and
reports tok/s, then reads `/api/ps` (`size` vs `size_vram`) and prints a verdict:

- **`100% GPU`** — fully offloaded to the Arc. This is the goal.
- **`100% CPU`** — *not* accelerated: Vulkan/Arc was not used. **First check for
  an integrated GPU being dropped:** if the backend log shows
  `dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1` (common on Intel
  Arc iGPUs like the Lunar Lake **Arc 140V** and on Iris Xe), set
  `OLLAMA_IGPU_ENABLE=1` (see the env-var table above) and restart Ollama — that
  alone flips the same models from `100% CPU` to `100% GPU`. The desktop app sets
  this automatically on Intel hosts. Only if the flag doesn't help: confirm your
  Ollama version supports this GPU, and as a last resort try Intel's **ipex-llm**
  portable Ollama build.
- **partial split** — the model doesn't fit in Arc VRAM alongside the second
  resident model (`OLLAMA_MAX_LOADED_MODELS=2`). Use a smaller quant or lower
  that limit.

Pass `-Model`, `-OllamaHost`, or `-LogPath` to override the defaults (do **not**
pass `embedding-model` to `-Model` — it has no `/api/generate` endpoint).

> Task Manager's default GPU view reads **0%** during CUDA inference because it
> shows the *3D* engine. Trust `ollama ps` / `size_vram` and the tok/s figure
> instead.

---

## Sharing the graph database

The populated graph lives in the **native Neo4j data directory**, which is not
part of the repo. If you just share the code, a coworker gets an **empty**
database and would have to re-run the entire `ingest → load_manifest → enrich`
pipeline — which needs all the source documents *and* burns a lot of host LLM
time. To skip that, ship them a **snapshot** of the graph.

Three things to keep in mind:

- **A dump only loads into the same Neo4j major line it came from.** The current
  graph is on the `2026.08.x` line (the shipped server is Community 2026.08.1). If you move lines, re-export with `scripts/stage-neo4j.ps1 -Dump … -ReExport`.
- **Community cannot load an Enterprise `block` dump.** Enterprise (what Neo4j
  Desktop installs) defaults to `block`; a dump destined for a Community server —
  including the one the desktop app ships — must be a **record** format
  (aligned/standard). See [`DECONTAINERIZE_PLAN.md`](DECONTAINERIZE_PLAN.md).
- **Sharing the graph does not remove the Ollama dependency.** The coworker still
  needs host-native Ollama running to *query* (embedding the question, entity
  extraction, chat). The snapshot only saves them the rebuild.

Both scripts drive the host's `neo4j-admin` directly and **do not manage the
server lifecycle** — stop the database yourself first. They refuse to run while
bolt (`127.0.0.1:7687`) is still open.

### You — export

```powershell
pwsh -File scripts/export-graph.ps1 `
  -Neo4jAdmin "$env:USERPROFILE\.Neo4jDesktop2\Data\dbmss\dbms-<id>\bin\neo4j-admin.bat" `
  -JavaHome  "$env:USERPROFILE\.Neo4jDesktop2\Cache\runtime\zulu21..."
```

This writes `snapshot/neo4j.dump`, carrying **all nodes, embeddings, and the
`chunk_vector_idx` vector-index config** — nothing needs rebuilding on the other
end. Start Neo4j again afterward.

`snapshot/` is **gitignored** because a dump with embeddings is large (tens–
hundreds of MB). Don't commit it; share it via **Git LFS** or send the `.dump`
out-of-band (drive/USB).

### Coworker — import

After cloning the repo, drop the shared `neo4j.dump` into a `snapshot/` folder at
the repo root, stop Neo4j, then:

```powershell
pwsh -File scripts/import-graph.ps1 `
  -Neo4jAdmin "<...>\bin\neo4j-admin.bat" -JavaHome "<...jre...>"
```

This **replaces** the local database (`--overwrite-destination=true`), so any
existing local graph is discarded. Start Neo4j again afterward; the vector index
rebuilds on startup. Host-native Ollama must be installed and running (see the
one-time setup above) for chat to work.

---

## Reverting the Docker-era network exposure

Earlier versions of this stack required `OLLAMA_HOST=0.0.0.0` so the API
*container* could reach Ollama across the Docker bridge, which exposed Ollama's
unauthenticated API on every interface — and a firewall-hardening procedure to
contain it. **Both are retired**: the native API uses loopback, so Ollama binds
`127.0.0.1` only and there is nothing to harden.

If you ran the old setup on this machine, undo it:

1. **Remove the env var** if it is still persisted:
   `[Environment]::SetEnvironmentVariable("OLLAMA_HOST", $null, "User")` on
   Windows (or `launchctl unsetenv OLLAMA_HOST` on macOS), then restart Ollama.
   The desktop wizard does this for you on launch.
2. **Revert the firewall rules** — they are scoped to a Docker subnet that no
   longer exists: `pwsh -File scripts/harden-ollama-firewall.ps1 -Revert`.
3. Confirm Ollama is loopback-only: `curl http://127.0.0.1:11434/api/version`
   succeeds, and the same request to the machine's LAN address does not.

`scripts/harden-ollama-firewall.ps1` is kept **only** for that `-Revert` path and
should not be used to apply new rules.

---

## Tuning knobs

The startup behaviour is configurable in [`src/core/config.py`](../src/core/config.py)
(override via `.env`): `ollama_startup_retries`, `ollama_startup_delay`,
`ollama_request_timeout`, `ollama_pull_timeout`, `chat_base_model`,
`embedding_base_model`. The base-model names **must** match the `FROM` lines in
the two Modelfiles.
