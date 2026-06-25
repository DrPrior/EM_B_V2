# Hybrid Setup — Host-Native Ollama

This app runs in a **hybrid** architecture: **Neo4j** and the **Python API** run
in Docker, while **Ollama runs natively on the host machine** so it can use the
host GPU directly (Apple **Metal**, NVIDIA **CUDA**, or Intel Arc **Vulkan**)
without the performance loss of GPU passthrough into a Linux container.

The API container reaches the host's Ollama at `http://host.docker.internal:11434`
and **provisions its models automatically on startup** — you do **not** need to
pull models or build the custom variants by hand. You only need to install
Ollama and configure it to accept traffic from the container.

---

## One-time host setup

### 1. Install Ollama natively

- **macOS (Apple Silicon):** install the [Ollama macOS app](https://ollama.com/download)
  or `brew install ollama`. Metal acceleration works out of the box.
- **Windows (NVIDIA or Intel Arc):** run the official `OllamaSetup.exe` from
  <https://ollama.com/download>. NVIDIA uses CUDA automatically; modern Intel Arc
  GPUs are used via Vulkan.

### 2. Set the required host environment variables

These let the container talk to Ollama and keep both models resident in memory.

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_HOST` | `0.0.0.0` | Native Ollama listens only on `127.0.0.1` by default and **rejects** calls from the Docker bridge. Binding `0.0.0.0` lets the container reach it. |
| `OLLAMA_KEEP_ALIVE` | `-1` | Keep models loaded indefinitely so there is no reload lag between the embedding and chat steps of each query. |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Keep the 12B chat model and 4B embedding model co-resident; prevents Ollama from unloading one to make room for the other ("model thrashing"). |

> ⚠️ **Security note:** `OLLAMA_HOST=0.0.0.0` exposes the Ollama API on **all
> network interfaces**, not just localhost — anyone who can reach this machine on
> port `11434` can use it. This is fine on a trusted dev machine behind a
> firewall. On an untrusted network, restrict port `11434` with the host
> firewall (allow only the Docker bridge / loopback).

> ℹ️ **Persistence:** Ollama re-reads these variables **every time the daemon
> starts**, so what matters is whether they're stored persistently in the OS. Set
> them with the methods below (not with a per-shell `$env:` / `export`, which
> only lasts for that session). The *models* themselves are never persistent —
> after an Ollama restart or reboot, VRAM starts empty and models reload on the
> first query, then stay resident because `OLLAMA_KEEP_ALIVE=-1` is still in
> effect.

**Windows (persists permanently):**
1. Search the Start Menu for **"Edit the system environment variables"**.
2. Add the three **System variables** above (or use `setx OLLAMA_HOST 0.0.0.0`, etc.).
3. Quit Ollama from the system tray and relaunch it.

Set once — every future restart and reboot picks them up automatically. (Do
**not** use `$env:OLLAMA_HOST="0.0.0.0"` in a PowerShell session; that is
session-only and won't survive.)

**macOS:**
```bash
launchctl setenv OLLAMA_HOST "0.0.0.0"
launchctl setenv OLLAMA_KEEP_ALIVE "-1"
launchctl setenv OLLAMA_MAX_LOADED_MODELS "2"
```
Then fully quit and relaunch the Ollama app.

> ⚠️ **macOS gotcha:** `launchctl setenv` survives an Ollama app restart but is
> **lost on reboot / logout** — you'd have to re-run it. For true persistence,
> add a **LaunchAgent** that sets them at login. Create
> `~/Library/LaunchAgents/com.ollama.env.plist`:
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
>     <string>launchctl setenv OLLAMA_HOST 0.0.0.0; launchctl setenv OLLAMA_KEEP_ALIVE -1; launchctl setenv OLLAMA_MAX_LOADED_MODELS 2</string>
>   </array>
>   <key>RunAtLoad</key><true/>
> </dict>
> </plist>
> ```
> Then `launchctl load ~/Library/LaunchAgents/com.ollama.env.plist` (it also runs
> automatically at each login). Relaunch the Ollama app afterward.

### 3. Verify Ollama is reachable

```bash
curl http://localhost:11434/api/version
```
You should get a JSON version string. If it hangs or refuses, Ollama isn't
running or `OLLAMA_HOST` isn't set.

---

## Start the stack

```bash
docker compose up -d --build
```

On startup the API will:

1. Wait for the host Ollama daemon (retries `ollama_startup_retries` times; if
   it never answers, the container **exits** with a clear message — start Ollama
   and bring the stack back up).
2. Pull the base models (`gemma4:12b-it-qat`, `qwen3-embedding:4b`) if missing —
   the first run downloads ~10 GB, so be patient.
3. Build the custom `chat-model` / `embedding-model` variants from
   [`Modelfile`](../Modelfile) and [`Modelfile.embeddings`](../Modelfile.embeddings)
   if missing.

Watch progress:
```bash
docker logs -f em_b_v2-api-1
```

Confirm the variants landed on the host:
```bash
ollama list   # should list chat-model and embedding-model
```

### Re-provisioning without a restart

If you change a Modelfile or need to rebuild a variant, re-run the bootstrap
without restarting the container:
```bash
curl.exe -s -X POST http://localhost:8000/admin/bootstrap-models
```

---

## Tuning knobs

The startup behaviour is configurable in [`src/core/config.py`](../src/core/config.py)
(override via `.env`): `ollama_startup_retries`, `ollama_startup_delay`,
`ollama_request_timeout`, `ollama_pull_timeout`, `chat_base_model`,
`embedding_base_model`. The base-model names **must** match the `FROM` lines in
the two Modelfiles.
