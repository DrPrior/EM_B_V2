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

> ⚠️ **Security note:** `OLLAMA_HOST=0.0.0.0` exposes the **unauthenticated**
> Ollama API on **all network interfaces**, not just localhost — anyone who can
> reach this machine on port `11434` can use it. This is fine on a trusted dev
> machine behind a firewall, but **not** on a laptop that roams onto untrusted
> Wi-Fi. Before using such a laptop off your trusted network, lock the port down
> — see [Hardening for untrusted networks](#hardening-for-untrusted-networks-laptops)
> below (a one-command script is provided).

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

## Sharing the graph database

The populated graph lives in a **named Docker volume** (`em_b_v2_neo4j_data`)
that is **not** part of the repo. If you just share the code, a coworker gets an
**empty** database and would have to re-run the entire
`ingest → load_manifest → enrich` pipeline — which needs all the source
documents *and* burns a lot of host LLM time. To skip that, ship them a
**snapshot** of the graph alongside the code.

Two things to keep in mind:

- **The Neo4j version is pinned** (`image: neo4j:2026.04.0` in
  [`docker-compose.yml`](../docker-compose.yml)) precisely so a snapshot exported
  on one machine is guaranteed to load on another — the store format must match.
  If you bump that version, re-export any shared snapshot.
- **Sharing the graph does not remove the Ollama dependency.** The coworker still
  needs host-native Ollama running to *query* (embedding the question, entity
  extraction, chat). The snapshot only saves them the rebuild.

### You — export

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export-graph.ps1
```

This stops Neo4j (the offline dump format requires it), writes
`snapshot/neo4j.dump`, and restarts Neo4j. The dump carries **all nodes,
embeddings, and the `chunk_vector_idx` vector-index config** — nothing needs
rebuilding on the other end.

`snapshot/` is **gitignored** because a dump with embeddings is large (tens–
hundreds of MB). Don't commit it directly — share it via **Git LFS** or send the
`.dump` out-of-band (email/drive/USB).

### Coworker — import

After cloning the repo, drop the shared `neo4j.dump` into a `snapshot/` folder at
the repo root, then — **before** the first `docker compose up`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\import-graph.ps1 -Up
```

This loads the dump into the local volume (**overwriting** any existing local
graph) and brings the stack up. Omit `-Up` to load only and start the stack
yourself later. Host-native Ollama must be installed and running (see the
one-time setup above) for chat to work.

---

## Hardening for untrusted networks (laptops)

`OLLAMA_HOST=0.0.0.0` is required so the API **container** can reach Ollama, but
it also puts Ollama's **unauthenticated** API on every network interface. Ollama
has no built-in auth and `OLLAMA_ORIGINS` is only CORS (not a network ACL), so
on a laptop that roams onto untrusted Wi-Fi, anyone on that network who can reach
`your-laptop:11434` can run your models, read/inject prompts, or exhaust the GPU.

The fix is at the **network layer**: keep Ollama on `0.0.0.0` for the OS, but let
the firewall admit port `11434` **only from the Docker subnet** and block it from
the physical LAN.

### Audit first — you may already be safe

Windows Firewall blocks unsolicited inbound by **default**, so on many machines
port `11434` is *already* closed to the network and **no change is needed**. The
exposure only exists if something (often the Ollama/Docker installer, or a user
clicking "Allow" on a firewall prompt) added an inbound **Allow** rule. So always
check before you change anything.

In an **elevated** PowerShell:

```powershell
# A. Any Allow rule scoped to the port?
powershell -ExecutionPolicy Bypass -File .\scripts\harden-ollama-firewall.ps1 -Audit

# B. Any Allow rule scoped to the ollama.exe *program* (port = Any)?
Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True |
  Where-Object { $_.DisplayName -match 'ollama' -or
    (($_ | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue).Program -match 'ollama') } |
  Select-Object DisplayName,
    @{n='Program';e={($_ | Get-NetFirewallApplicationFilter).Program}},
    @{n='LocalPort';e={($_ | Get-NetFirewallPortFilter).LocalPort}},
    @{n='RemoteScope';e={($_ | Get-NetFirewallAddressFilter).RemoteAddress -join ','}}

# C. Is the firewall on and defaulting to block?
Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction
```

Read the results:

- **B returns nothing**, **A shows no rule**, and **C** shows every profile
  `Enabled = True` with `DefaultInboundAction = Block` *or* `NotConfigured`
  (NotConfigured resolves to **Block** — the Windows default) → **the port is
  already closed to the LAN. You are done; do not apply the script** (adding a
  rule where the default already blocks gains nothing).
- **A or B shows an Allow rule** (especially `RemoteScope = Any`) → that is the
  exposure. Narrow it with the automated step below.

> The definitive test, since rule analysis can miss edge cases: from **another
> device on the same network**, run `curl http://<this-laptop-ip>:11434/api/version`.
> Timeout / connection-refused = safe; a JSON version string = exposed. (Testing
> from the laptop itself gives a false "exposed" — a host can always reach its
> own services.)

> Re-audit after Ollama updates: an update can re-trigger the "Allow this app
> through the firewall?" prompt, and clicking **Allow** re-opens the port.

### Windows — automated (recommended, only if the audit found an Allow rule)

Run the bundled script in an **elevated** PowerShell. Start the stack first and
send one chat so it can detect the exact Docker subnet, then:

```powershell
# inspect current exposure, change nothing
powershell -ExecutionPolicy Bypass -File .\scripts\harden-ollama-firewall.ps1 -Audit

# apply: disable broad Allow rules, add one scoped to the Docker subnet
powershell -ExecutionPolicy Bypass -File .\scripts\harden-ollama-firewall.ps1

# undo everything it changed
powershell -ExecutionPolicy Bypass -File .\scripts\harden-ollama-firewall.ps1 -Revert
```

The script auto-detects the Docker/WSL subnet(s) (e.g. `172.x.x.0/24`), falls
back to the well-known Docker Desktop ranges if the stack isn't connected, and
records its changes so `-Revert` is clean. Pass `-DockerSubnet "172.20.192.0/24"`
to force a specific range if detection is wrong.

### Windows — manual equivalent

```powershell
# 1. Find the broad Allow rule(s) for 11434 and disable any with scope = Any
Get-NetFirewallPortFilter -Protocol TCP | Where-Object { "$($_.LocalPort)" -eq "11434" } |
  Get-NetFirewallRule | Where-Object Direction -eq 'Inbound' |
  Select-Object DisplayName, Action, Enabled

# 2. Add ONE allow scoped to your Docker subnet; the default-block covers the LAN
New-NetFirewallRule -DisplayName "Ollama - Docker only" -Direction Inbound `
  -Protocol TCP -LocalPort 11434 -RemoteAddress 172.20.192.0/24 -Action Allow
```

### macOS — `pf` recipe

The built-in Application Firewall is too blunt (blocking "incoming to ollama" can
also kill the container path). Use `pf` to allow `11434` only on the Docker
bridge interface and block it elsewhere. Add to `/etc/pf.anchors/ollama`:

```
# Allow Docker Desktop's bridge to reach Ollama; block the physical NICs.
pass in quick on bridge100 proto tcp to any port 11434
block in quick proto tcp to any port 11434
```

Load it with `sudo pfctl -a ollama -f /etc/pf.anchors/ollama` (the bridge
interface name may differ — check `ifconfig` for the `vmenet`/`bridge` Docker
uses). Persist via an `/etc/pf.conf` anchor reference.

### Verify both halves

1. **App still works** — send a chat through the running stack (the container
   path must still reach Ollama).
2. **LAN is closed** — from **another device on the same network**:
   ```bash
   curl http://<this-laptop-ip>:11434/api/version   # must time out / be refused
   ```

If step 1 breaks, the allowed subnet is too tight — re-run the script with the
stack up, or pass the correct `-DockerSubnet`.

### Stronger options

- **Loopback + bridge:** keep Ollama on `127.0.0.1` (never on the LAN) and run a
  small port-forward that listens only on the Docker adapter (`netsh interface
  portproxy` on Windows, `socat` on macOS). More moving parts (the adapter IP can
  change), but Ollama is never LAN-exposed at all.
- **Run the app natively (the real long-term fix):** the `0.0.0.0` requirement
  exists *only because the orchestration app runs in Docker*. If the Python app
  runs natively on the laptop — or inside the planned desktop (Tauri/Electron)
  shell — it talks to Ollama over `127.0.0.1:11434` and this exposure disappears
  entirely. Neo4j can stay in Docker (the app reaches it, not the reverse). For a
  fleet of roaming, non-technical-user laptops, prefer this.

---

## Tuning knobs

The startup behaviour is configurable in [`src/core/config.py`](../src/core/config.py)
(override via `.env`): `ollama_startup_retries`, `ollama_startup_delay`,
`ollama_request_timeout`, `ollama_pull_timeout`, `chat_base_model`,
`embedding_base_model`. The base-model names **must** match the `FROM` lines in
the two Modelfiles.
