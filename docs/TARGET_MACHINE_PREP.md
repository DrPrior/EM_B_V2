# Target Machine Prep

What to do on each machine **before** handing over the USB drive. Doing this
first is not just a time-saver — it is what keeps the app's first run quiet
enough to survive managed-endpoint security. Budget 15–30 minutes per machine,
almost all of it downloading models.

Audience: whoever provisions the machines (you, or IT). Not the end user — they
get [`USB_README.txt`](USB_README.txt).

> **Decontainerized:** there is no Docker. Neo4j and the API ship as bundled
> assets and run as native processes; **Ollama is the only third-party runtime to
> pre-install.** For the maintainer workstation that *builds* the release, see
> [`DECONTAINERIZE_PLAN.md`](DECONTAINERIZE_PLAN.md).

---

## Why bother

The wizard can install Ollama itself if it's missing, but that path downloads a
remote executable and runs it silently — the classic dropper pattern behavioral
endpoint security flags, on exactly the IT-managed machines this app targets.
Pre-installing Ollama (a vendor-signed, IT-approved install) removes the trigger,
and pre-pulling the models means **first run makes no network requests at all.**

---

## 1. Ollama

Install from <https://ollama.com/download>.

Either a per-user install (`%LOCALAPPDATA%\Programs\Ollama`) or a per-machine one
(`%ProgramFiles%\Ollama`) works — the app checks both, and falls back to `ollama`
on `PATH`.

```powershell
ollama --version
```

## 2. Ollama environment variables

Set these as **user or system environment variables** (not per-session — they
must survive a reboot) so the models stay warm and co-resident:

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_KEEP_ALIVE` | `-1` | Keep models resident — otherwise every query pays a multi-second reload |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Hold the chat *and* embedding model at once |

```powershell
setx OLLAMA_KEEP_ALIVE -1
setx OLLAMA_MAX_LOADED_MODELS 2
```

**No `OLLAMA_HOST=0.0.0.0`** — the app is native and reaches Ollama over
`127.0.0.1`, so Ollama stays on its default loopback bind (no LAN exposure, no
firewall hardening needed). On Intel integrated GPUs you may also need
`OLLAMA_IGPU_ENABLE=1` (the wizard sets it there). **Restart Ollama afterward**
(quit from the system tray, reopen) so it picks the variables up.

Skipping this isn't fatal — the app sets them itself — but then it force-quits
and relaunches Ollama, one more thing for endpoint security to notice.

## 3. Base models

This is the ~10 GB download — doing it here is the difference between a fully
offline first run and one that pulls 10 GB over the user's connection.

```powershell
ollama pull gemma4:12b-it-qat
ollama pull embeddinggemma:latest
```

**Pull the base models only.** Do *not* hand-build the `chat-model` /
`embedding-model` variants — the app builds them from the Modelfiles it ships, so
they carry the right parameters (`num_ctx 8192`, the RAG system prompt, the
768-dim embedding). The wizard only checks whether a variant *exists*, so a
hand-built one from a stale Modelfile would be silently accepted with the wrong
settings. Building them in-app is local and fast — you give up nothing.

---

## Verify

```powershell
ollama --version                                                # a version
ollama list                                                     # both base models
[Environment]::GetEnvironmentVariable('OLLAMA_KEEP_ALIVE','User')  # -1
```

`ollama list` should show `gemma4:12b-it-qat` and `embeddinggemma:latest`. If
`chat-model` / `embedding-model` also appear, this machine has already run the
app — fine; setup skips past them.

---

## What the app does on first run

Nothing above removes these; they are the app's actual work, all reading from the
USB (no network on a prepared machine):

1. Build the `chat-model` / `embedding-model` variants — **local, no network**
2. Unpack the bundled Neo4j server + JRE and the frozen API
3. Set the local Neo4j password
4. Extract the document corpus to `%APPDATA%\EM Knowledge Assistant`
5. Load the prebuilt graph dump (offline)
6. Start Neo4j + the API (native) and wait for health

Expect 10–20 minutes. Leave the drive plugged in for the whole run; it is never
needed again afterward.

---

## Known limitation: unsigned binaries are blocked

Prepping the machine does **not** get the app past a "blocked by your system
administrator" block. On these machines **WDAC Code Integrity is enforced** (and
AppLocker is active), so an **unsigned** executable — the installer *and* the
bundled `emb-api.exe` — is refused execution outright. It is a policy block, not
a privilege one: running as Administrator does not bypass it.

That needs a code-signing certificate. The build is configured for one
(`electron/package.json` → `win.signtoolOptions`; `build-release.ps1 -CertSubject`
signs `emb-api.exe`), publisher *University of Arkansas at Little Rock*. Until the
certificate is supplied, the build ships unsigned and will not run on the fleet.
Machine prep quiets endpoint security *after* install; signing is what lets it run
at all.
