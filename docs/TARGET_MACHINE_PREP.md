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

Set these as **user or system environment variables** (not per-session; they
must survive a reboot). This is the complete set the app checks for
(`REQUIRED` in `electron/lib/ollamaenv.js`). If any one is missing or different,
the app sets it and restarts Ollama on first run. So set **all five**; a partial
set still triggers the restart this step exists to avoid.

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_KEEP_ALIVE` | `-1` | Keep models resident; otherwise every query pays a multi-second reload |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Hold the chat *and* embedding model at once |
| `OLLAMA_FLASH_ATTENTION` | `1` | Faster prompt processing; harmless where unsupported |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Roughly halves KV-cache memory (needs flash attention) |
| `OLLAMA_NUM_PARALLEL` | `1` | One inference slot; stops mid-session model reloads on shared-memory GPUs |

```powershell
setx OLLAMA_KEEP_ALIVE -1
setx OLLAMA_MAX_LOADED_MODELS 2
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
setx OLLAMA_NUM_PARALLEL 1
```

**Intel-only machines** (an Intel Arc / Iris Xe GPU and no NVIDIA card) also need
these two. The app adds them only on such machines. Don't set them on NVIDIA hosts:

```powershell
setx OLLAMA_VULKAN 1
setx OLLAMA_IGPU_ENABLE 1
```

**No `OLLAMA_HOST=0.0.0.0`.** The app is native and reaches Ollama over
`127.0.0.1`, so Ollama stays on its default loopback bind (no LAN exposure, no
firewall hardening needed). If an older build left `OLLAMA_HOST=0.0.0.0` in the
user environment, the app removes it. **Restart Ollama afterward** (quit from the
system tray, reopen) so it picks the variables up.

Skipping this isn't fatal, because the app sets them itself. But then it
force-quits and relaunches Ollama, one more thing for endpoint security to notice.

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
'OLLAMA_KEEP_ALIVE','OLLAMA_MAX_LOADED_MODELS','OLLAMA_FLASH_ATTENTION',
'OLLAMA_KV_CACHE_TYPE','OLLAMA_NUM_PARALLEL' |
  ForEach-Object { "{0,-26} {1}" -f $_, [Environment]::GetEnvironmentVariable($_,'User') }
# expect: -1, 2, 1, q8_0, 1
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
administrator" block. It is a policy block, not a privilege one: running as
Administrator does not bypass it.

**What was observed** (UALR-managed Windows 11, 2026-09-17): launching the bundled
`emb-api.exe` fails with a bare `Access is denied.` The cause is Microsoft
Defender **Attack Surface Reduction** rule `01443614-CD74-433A-B99E-2ECDC07BFC25`,
*"Block executable files from running unless they meet a prevalence, age, or
trusted list criterion"*, in Block mode. It shows up as event **1121** in
`Microsoft-Windows-Windows Defender/Operational`, and **not** in the AppLocker log.
The rule is deployed by policy (Intune), so `Get-MpPreference` doesn't list it.

```powershell
Get-WinEvent -LogName "Microsoft-Windows-Windows Defender/Operational" |
  Where-Object Id -eq 1121 | Select-Object -First 5 TimeCreated, Message
```

**What needs signing.** Microsoft describes this rule as covering `.dll` files as
well as `.exe`, so signing the app's main exe alone may not be enough. An audit
of v0.4.0 (2026-09-23) found **31 unsigned binaries**; everything else ships
vendor-signed (the Java runtime by Eclipse, Neo4j by Apache, most of the Python
runtime by Anaconda/Microsoft):

| Where | Unsigned files |
|---|---|
| Installer | `EM Knowledge Assistant-Setup-0.4.0.exe` |
| Desktop app | `EM Knowledge Assistant.exe`, `resources\elevate.exe`, `ffmpeg.dll`, `libEGL.dll`, `libGLESv2.dll`, `vk_swiftshader.dll`, `vulkan-1.dll`, `dxcompiler.dll` |
| API bundle (`emb-api.zip`) | `emb-api.exe` + 21 `.dll`/`.pyd` under `_internal\` (OpenSSL, `pydantic_core`, `cryptography`, `lxml`, `pywin32`, `psutil`, `wrapt`, `yaml`, PIL's `_avif`) |

The fix is one of: sign all 31 with the UALR certificate; get the certificate onto
the organization's trusted list (a brand-new certificate can still fail the
rule's *prevalence* test); or have IT exclude the app's install folder from this
rule. The build is prepared for signing (`electron/package.json` →
`win.signtoolOptions`, publisher *University of Arkansas at Little Rock*). But
`build-release.ps1 -CertSubject` currently signs **only `emb-api.exe`**, and needs
extending to cover the `_internal` binaries once the certificate exists. Until
then, the build is unsigned and will not run on the fleet. Machine prep quiets
endpoint security *after* install; signing is what lets it run at all.
