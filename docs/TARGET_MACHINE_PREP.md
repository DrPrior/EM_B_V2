# Target Machine Prep

What to do on each machine **before** handing over the USB drive. Doing this
first is not just a time-saver — it is what keeps the app's first run quiet
enough to survive managed-endpoint security. Budget 20–40 minutes per machine,
almost all of it downloading.

Audience: whoever provisions the machines (you, or IT). Not the end user — they
get [`USB_README.txt`](USB_README.txt).

> For the maintainer workstation that *builds* the release, see
> [`HYBRID_SETUP.md`](HYBRID_SETUP.md) instead. This document is about the
> machines that only *run* the finished app.

---

## Why bother

The wizard can install Docker and Ollama itself, and it will still do so if it
finds them missing. But that path downloads a remote executable and runs it
silently (`OllamaSetup.exe /SILENT`, `Docker Desktop Installer.exe install`).
That is the classic dropper pattern, and behavioral endpoint security flags it —
on exactly the IT-managed machines this app is aimed at.

Provisioning by hand removes the trigger completely and reframes the software
politically: Docker and Ollama become IT-approved, vendor-signed installs rather
than something an unsigned installer pulled down at runtime.

With all four steps done, **first run makes no network requests at all.**

---

## 1. Docker Desktop

Install from <https://www.docker.com/products/docker-desktop/>.

Requires administrator rights, WSL2, and usually a reboot on first install. Let
it finish completely and confirm the whale icon is running in the system tray
before moving on.

```powershell
docker info --format '{{.ServerVersion}}'
```

Must print a version. If it errors, Docker is installed but the daemon is not
up — start Docker Desktop and wait.

## 2. Ollama

Install from <https://ollama.com/download>.

Either a per-user install (`%LOCALAPPDATA%\Programs\Ollama`) or a per-machine
one (`%ProgramFiles%\Ollama`) works — the app checks both, and falls back to
`ollama` on `PATH` if you installed somewhere else entirely.

```powershell
ollama --version
```

## 3. Ollama environment variables

The API runs in a container and reaches Ollama across the Docker bridge, which
only works if the daemon binds every interface. Set these three as **user or
system environment variables** (not per-session — they must survive a reboot):

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_HOST` | `0.0.0.0` | Bind all interfaces so the container can reach the host daemon |
| `OLLAMA_KEEP_ALIVE` | `-1` | Keep models resident — otherwise every query pays a multi-second reload |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Hold the chat *and* embedding model at once |

```powershell
setx OLLAMA_HOST 0.0.0.0
setx OLLAMA_KEEP_ALIVE -1
setx OLLAMA_MAX_LOADED_MODELS 2
```

**Restart Ollama afterward** (quit from the system tray, reopen) so the daemon
picks them up. `setx` writes the registry but does not touch already-running
processes.

Skipping this step is not fatal — the app detects it and sets them itself — but
then it has to force-quit and relaunch Ollama, which is one more thing for
endpoint security to notice. Setting them here keeps that path dormant.

> Binding `0.0.0.0` exposes Ollama on the LAN. On laptops that leave a trusted
> network, see the firewall hardening section in
> [`HYBRID_SETUP.md`](HYBRID_SETUP.md#hardening-for-untrusted-networks-laptops).

## 4. Base models

This is the ~10 GB download. Doing it here is the difference between a first run
that is fully offline and one that pulls 10 GB over the user's connection.

```powershell
ollama pull gemma4:12b-it-qat
ollama pull qwen3-embedding:4b
```

**Pull the base models only.** Do *not* hand-build the `chat-model` /
`embedding-model` variants — leave those to the app.

The variants carry real behavior from the Modelfiles: `num_ctx 8192` (Ollama's
2048 default silently truncates conversation history), `temperature 0`, and the
RAG system prompt. The wizard only checks whether a variant *exists*, not what is
inside it, so a hand-built variant from a stale Modelfile would be silently
accepted and the app would run with wrong parameters. Letting the app build them
guarantees they match the Modelfiles shipped inside that specific installer.

Building them is local and fast — you give up nothing.

---

## Verify

```powershell
docker info --format '{{.ServerVersion}}'                       # a version
ollama --version                                                # a version
ollama list                                                     # both base models
[Environment]::GetEnvironmentVariable('OLLAMA_HOST','User')     # 0.0.0.0
```

`ollama list` should show `gemma4:12b-it-qat` and `qwen3-embedding:4b`. If
`chat-model` and `embedding-model` also appear, this machine has already run the
app — that is fine and setup will skip straight past them.

---

## What the app still does on first run

Nothing above removes these; they are the app's actual work:

1. Build the `chat-model` and `embedding-model` variants — **local, no network**
2. `docker load` the API image from the USB
3. `tar -xzf` the document corpus to `%APPDATA%\EM Knowledge Assistant`
4. Import the Neo4j graph snapshot
5. `docker compose up` and wait for health

All of it reads from the USB. Expect 10–20 minutes. Leave the drive plugged in
for the whole run; it is never needed again afterward.

---

## Known limitation: the installer is unsigned

Prepping the machine does **not** help the installer get past a
"blocked by your system administrator" message. That block is AppLocker / WDAC /
SmartScreen-for-Business policy, applied to the installer file before any of this
code runs — and it is not a privilege problem, so running as Administrator does
not bypass it.

That needs a code-signing certificate. The build is already configured for one
(`electron/package.json` → `win.signtoolOptions`, publisher
*University of Arkansas at Little Rock*); until a certificate is supplied,
electron-builder silently skips signing and ships an unsigned installer.

The two problems are independent. Machine prep quiets endpoint security *after*
the app is installed; signing is what gets it installed in the first place.
