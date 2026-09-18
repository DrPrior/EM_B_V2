# EM Knowledge Assistant — Desktop app

> **Native — no Docker anywhere.** The supervisor spawns Neo4j (bundled server +
> JRE) and the frozen API exe directly and ensures host-native Ollama. See
> [`../docs/DECONTAINERIZE_PLAN.md`](../docs/DECONTAINERIZE_PLAN.md) for what is left (release artifacts, signing)
> and for the **Defender ASR rule that currently prevents `emb-api.exe` from
> running on managed machines** — the first thing to resolve before any
> end-to-end test.

Electron wrapper that turns the EM_B_Hybrid stack into a one-click desktop app
for **Windows** and **macOS**. It is a *supervisor + first-run installer*:

1. On **first run**, guides the user through provisioning: Ollama → language
   models (~10 GB) → native Neo4j (+ JRE) → the frozen API bundle → the source
   corpus → the knowledge-graph snapshot → starting the stack.
2. On **later runs**, waits for its dependencies and brings the app up. It also
   re-installs the API bundle if the shipped manifest is newer than what's on
   disk (see *In-place updates*).
3. Loads the existing web UI at `http://127.0.0.1:8000` in its window.

**Delivery: USB drive, no download server.** The heavy *custom* assets (frozen
API bundle, Neo4j, JRE, graph snapshot, corpus) ship in an `assets/` folder on
the USB, read locally at setup time — the USB only needs to be plugged in during
first run. Only the Ollama installer and the ~10 GB base models come from the
internet, and only when the machine wasn't pre-provisioned.

Ollama is **host-native** so it uses the GPU. GPU acceleration is Ollama's job
and auto-detected: CUDA (Nvidia), Vulkan (Intel Arc / iGPU — experimental),
Metal (Apple Silicon), or CPU fallback.

## Layout

```
electron/
  main.js            app lifecycle + window; runs wizard or fast-start, then
                     navigates to http://127.0.0.1:8000
  preload.js         contextIsolated bridge (window.api)
  supervisor.js      start/stop native Neo4j + API, /health polling, quickStart fast path
  lib/
    firstrun.js      guided first-run orchestrator (the step sequence)
    assets.js        locate the USB `assets/` folder (auto-detect + verify)
    apibundle.js     install the frozen API bundle; reinstall it after an in-place update
    archive.js       zip / tar.gz extraction via the OS `tar`
    procs.js         spawn + readiness-check the Neo4j and API child processes
    logger.js        rotating electron.log (or console in dev)
    ollama.js        detect/install Ollama, pull bases + build variants (streamed)
    ollamaenv.js     persist host OLLAMA_* env vars (setx / launchd agent) + restart
    modelfile.js     Node port of ollama_bootstrap._parse_modelfile
    snapshot.js      Node port of scripts/import-graph.ps1 (offline dump load)
    envfile.js       per-install desktop.env (random, stable Neo4j password)
    download.js      streaming downloader w/ progress + SHA-256 verify + cache
    gpu.js           best-effort GPU detection (messaging only)
    paths.js         userData + bundled-resource locations
  wizard/            offline setup UI (html/css/js), no CDN
  resources/
    assets.manifest.json   filenames + SHA-256s for the USB assets (+ Ollama URLs)
  scripts/
    build-release.ps1      freeze the API, zip Neo4j/JRE, stage dump + corpus,
                           update the manifest
    vendor-assets.ps1      refresh src/static/vendor (Tailwind, marked)
```

Related files at the repo root: `emb-api.spec` + `run_api.py` (the frozen API the
supervisor spawns), `.env.example`.

## Tests

Unit tests use Node's built-in runner (no extra deps):

```bash
npm test        # runs test/**/*.test.js
```

`test/ollamaenv.test.js` covers the pure host-env logic (`computeNeedsSetup`, the
LaunchAgent plist/path, `REQUIRED`). The process-spawning paths
(`ensure`/`persist*`/`restartOllama`, which call `setx`/`launchctl`/`taskkill`
and restart Ollama) are intentionally **not** unit-tested — validate those on a
real machine via the verification checklist below.

`test/apibundle.test.js` covers API-bundle install and in-place update against
real temp dirs with a fake extractor: the version/checksum comparison, replacing
an old bundle wholesale, and that a missing/wrong USB, a bad archive, or an
interrupted swap never leaves the previous install broken.

`test/procs.test.js` covers the readiness probes against throwaway local
HTTP/TCP listeners — `/health` must be 200 *and* `{"status":"healthy"}`, a
non-JSON body or a dead port is "not ready" rather than an exception, and the
waits are bounded. This is the ordering Docker's `depends_on: service_healthy`
used to provide.

`test/archive.test.js` runs against the real OS `tar` and pins the positional
contract shared by `build-release.ps1`, `lib/archive.js` and `lib/paths.js`: a
contents-at-root zip must land at `<userData>/api/emb-api.exe` with no extra
nesting, and `project_data.tar.gz` must keep its top-level directory.

`test/envfile.test.js` pins `parseEnv` and, above all, that the generated Neo4j
password **survives a second call** — it is baked into the store on first run, so
regenerating it would lock the app out of its own graph.

`test/snapshot.test.js` covers the import-once marker, including the cases that
must force a re-import (a marker naming a different Neo4j home, and a legacy
marker with no `dataDir`), plus the load→migrate sequence: that `migrate` is
called after `load` and **without** `--to-format` (which would risk an
Enterprise-only store), that a failed `load` is fatal and leaves no marker, and
that a failed `migrate` is reported but does not abort the import.

`test/electron-stub.js` is a helper, not a suite: it seeds the module cache so
`require('electron')` yields a fake `app`, which is what lets modules reaching
`lib/paths.js` run under plain `node --test`.

`supervisor.js` and `firstrun.js` have **no** unit tests — their behaviour is
process orchestration and multi-GB I/O. Validate them with the checklist below.

### In-place updates

A new app build ships a new `assets.manifest.json` but keeps the first-run
marker, so launches take the fast path. Before starting the stack, `main.js`
runs `lib/apibundle.js`: the installed bundle carries a
`.installed-bundle.json` marker (manifest `version` + `apiBundle.sha256`), and
on a mismatch the new `emb-api.zip` is read from the USB `assets/` folder
(prompting for it if needed), verified, extracted to `api.new/`, and swapped in.
Only the API bundle is updated this way; Neo4j, the JRE, the snapshot, and the
corpus are still installed once, at first run.

## Preparing a USB drive (maintainer)

Two build steps, then copy onto the stick. **Order matters**: build the assets
first (it updates the manifest), then build the installers (they bake the
manifest in).

### 1. Build the custom assets

Do this on a machine that has a **fully built, enriched graph** (ran
ingest → load_manifest → enrich), the `project_data/` corpus on disk, the Python
runtime deps installed (for PyInstaller), a configured **Neo4j Community** home
and a redistributable JRE.

```powershell
pwsh -File electron/scripts/build-release.ps1 -Neo4jHome C:\stage\neo4j -JreHome C:\stage\jre
```

This produces in `release/`:

| File | How the app uses it |
|---|---|
| `emb-api.zip` | the frozen API; unpacked to `<userData>/api/emb-api.exe` + `_internal/` |
| `neo4j-community.zip` | unpacked to `<userData>/neo4j`; run as `neo4j console` |
| `jre.zip` | unpacked to `<userData>/jre`; `JAVA_HOME` for Neo4j |
| `neo4j.dump` | loaded offline via `neo4j-admin database load` on first run |
| `project_data.tar.gz` | extracted to `<userData>/project_data` (citation downloads) |

Each zip must unpack with its contents at the **root** — that positional contract
is shared by `build-release.ps1`, `lib/firstrun.js` and `lib/paths.js`.

It also records each file's name + SHA-256 in
`electron/resources/assets.manifest.json` (verified off the USB at setup time),
and sets the manifest `version`, which must match `package.json`'s. Pass
`-CertSubject` to code-sign `emb-api.exe` before zipping; without it the script
warns, and the unsigned exe **will not run** on a machine with UALR's Defender
ASR policy. The Ollama installer and the base models are fetched online, so they
are not in this bundle.

### 2. Build the installers

```bash
cd electron
npm install
npm run dist:win     # NSIS .exe   (run on Windows)
npm run dist:mac     # .dmg        (run on macOS)
```

Output lands in `electron/dist/`. Builds are **unsigned** for now — users get an
"unidentified developer" warning (Windows SmartScreen → *More info → Run anyway*;
macOS → right-click *Open*). See *Deferred* below.

### 3. Lay out the USB drive

```powershell
pwsh -File scripts/stage-usb.ps1 -Destination E:\ -Verify   # or omit -Destination
```

`scripts/stage-usb.ps1` assembles the whole drive layout. It builds nothing —
it checks that the installer's *baked-in* manifest matches
`electron/resources/assets.manifest.json` (catching "assets rebuilt but
installer wasn't", which otherwise surfaces as a checksum error on the user's
machine), verifies every asset in `release/`, robocopies the layout, and with
`-Verify` re-hashes what landed. With no `-Destination` it stages into
`usb-staging/` for review.

```text
USB drive
  EM Knowledge Assistant-Setup-0.4.0.exe   (and/or the .dmg)
  README.txt                                ← from docs/USB_README.txt
  TARGET_MACHINE_PREP.md                    ← from docs/TARGET_MACHINE_PREP.md
  assets/                                   ← the whole release/ folder
    emb-api.zip
    neo4j-community.zip
    jre.zip
    neo4j.dump
    project_data.tar.gz
  explainer/                                ← from docs/explainer/ (maintainer
    index.html ...                            docs; -SkipExplainer to omit)
```

The app auto-detects `assets/` (removable drives, or next to the installer). If
it can't, it shows a folder picker — the user selects the `assets` folder. The
folder is validated (it must contain the manifest's `apiBundle` file) and
remembered, so an interrupted setup resumes without re-picking.

`docs/USB_README.txt` is the end-user-facing instructions (SmartScreen warning,
"leave the USB plugged in", troubleshooting). Keep the version string in it in
sync with `electron/package.json`.

### 4. Prep the target machines

`docs/TARGET_MACHINE_PREP.md` is the procedure for whoever provisions the
machines: install Ollama, set the `OLLAMA_*` env vars, and `ollama pull` the two
**base** models. Done first, first run makes no network requests at all.

This matters beyond convenience. The wizard's fallback path downloads and
silently executes third-party installers — the dropper pattern behavioral
endpoint security flags, on precisely the managed machines this app targets.
Pre-provisioning keeps that path dormant.

Pull the bases only; let the app build the `chat-model` / `embedding-model`
variants. `ensureModels()` checks only that a variant *exists*, not what is in
it, so a hand-built variant from a stale Modelfile is silently accepted and the
app runs with wrong parameters (notably `num_ctx`). Building them in-app ties
them to the Modelfiles shipped in that installer.

## Develop / smoke-test the shell

```bash
cd electron
npm install
npm start
```

In dev, bundled resources resolve from the repo root instead of
`resourcesPath`. To exercise the real first-run flow you need the release assets
built; point the app at them with `EMB_ASSETS_DIR=<path to release/>` (or let the
picker find them). To re-trigger first-run, delete the markers under the app's
userData dir: `first-run-complete.json`, `graph-imported.json`,
`data-ready.json`, `desktop.env`, `assets-dir.json`.

## First-run flow details

- **Setup assets**: the API bundle, Neo4j, JRE, snapshot, and corpus are read
  from the USB `assets/` folder — auto-detected (removable drives / next to the
  app / a saved path / `$EMB_ASSETS_DIR`) or chosen via a folder picker, then
  verified against the manifest SHA-256s. The USB is only needed during first run.
- **Neo4j**: the zipped server and JRE are unpacked under userData, then
  `neo4j-admin dbms set-initial-password` runs **before** the first start —
  mandatory, because Neo4j bakes the password into the data dir on init. The
  server itself is started later, by the `start` step, as `neo4j console` with
  `JAVA_HOME` pointed at the bundled JRE.
- **Ollama**: gated on *installed-ness*, not liveness. Not answering on
  `127.0.0.1:11434` does not mean absent — `isInstalled()` checks the per-user
  and per-machine install dirs plus `ollama` on `PATH`, and a present-but-stopped
  daemon is **started**, never reinstalled over. Only a genuinely missing Ollama
  triggers the installer download. The wizard then pulls any missing base models
  and builds the `chat-model` / `embedding-model` variants with a progress bar
  (`/api/pull` + `/api/create`, streamed). Because the variants are built here,
  the API's own startup bootstrap hits its instant warm path. On a machine
  prepped per `docs/TARGET_MACHINE_PREP.md` the pull is skipped and only the
  local variant build runs.
- **Ollama host env** (`lib/ollamaenv.js`): the native API reaches Ollama over
  loopback, so Ollama keeps its default `127.0.0.1` bind and `OLLAMA_HOST` is
  **not** set. The wizard **persists** the warmth/throughput vars
  (`OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_MAX_LOADED_MODELS=2`, flash attention, q8_0
  KV cache, `OLLAMA_NUM_PARALLEL=1`) — via `setx` (user registry) on Windows, and
  via `launchctl setenv` **plus a RunAtLoad LaunchAgent** on macOS so they
  survive a reboot/logout (plain `launchctl setenv` doesn't). It also **removes**
  a user-scope `OLLAMA_HOST=0.0.0.0` left by a Docker-era build (any other value
  is left alone). It then restarts Ollama so the running daemon picks them up.
  Idempotent: skipped once the values are in place, and re-checked on every
  launch (`quickStart`) to self-heal drift.
- **Credentials**: a random Neo4j password is generated once into `desktop.env`
  and reused forever (it's baked into the Neo4j data dir on first DB start).
  `envfile.js` hands the children `NEO4J_AUTH`, `DB_URI=bolt://127.0.0.1:7687`
  and `DATA_ROOT` as **process env**. Neo4j and the API bind `127.0.0.1` only.
- **Graph**: the snapshot is loaded offline (Neo4j stopped) with the bundled
  `neo4j-admin database load`, then `database migrate` brings the store up to the
  bundled server's format version — the slow ingest/enrich pipeline is skipped
  entirely. The marker records the target data dir, so a relocated install
  re-imports instead of coming up empty.

  The migrate is a **backstop, not the mechanism**: it costs about a second when
  there is nothing to do, and it is deliberately non-fatal, because the server
  start moments later is the real verdict. The dump you ship should already be at
  the bundled server's format version — that is what
  `scripts/stage-neo4j.ps1 -ReExport` produces. It must also be a
  Community-loadable record/aligned dump, never Enterprise `block`.

## Verification (per plan)

On a clean machine/VM. **Blocked today:** Defender ASR rule
`01443614-CD74-433A-B99E-2ECDC07BFC25` (Block mode under UALR policy) stops the
unsigned `emb-api.exe` from launching at all — `Access is denied.` with nothing
in AppLocker. Clear that (signing accepted by policy, or an ASR exclusion) before
running this list; see `../docs/DECONTAINERIZE_PLAN.md`.

1. **Windows + Nvidia** — install → wizard completes → chat streams an answer →
   a citation link downloads its source file (validates the `project_data`
   mount). Confirm GPU use with `ollama ps`.
2. **Windows + Intel Arc / iGPU** — completes and answers (Vulkan or CPU
   fallback), even if slower.
3. **Windows, no GPU** — CPU fallback works; wizard reports "CPU" acceleration.
4. **macOS (Apple Silicon)** — completes with Metal.
5. **Restart** — quit + relaunch: wizard is skipped, stack comes up from the
   persisted data dir, UI works offline (vendored Tailwind/marked).
6. **Teardown** — quit and confirm no orphaned `neo4j`/`java` or `emb-api`
   processes remain and 7687/8000 are free. Docker used to give this for free;
   `lib/procs.js` owns it now, and it is untested outside a real run.
7. **Backend tests** run in your own env: `pytest` from the repo root.

## Deferred (structured, no rework)

- **Code signing / notarization**: `win.signtoolOptions` is present but has no
  `certificateSubjectName`, and `build-release.ps1` takes `-CertSubject` for the
  API exe; both need the UALR certificate. macOS needs `mac.notarize`. Not
  cosmetic — see the ASR note above.
- **Auto-update**: add `electron-updater` + an update feed. The versioned
  manifest + `lib/apibundle.js` already install a new API bundle in place.
