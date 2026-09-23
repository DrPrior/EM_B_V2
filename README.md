# EM Knowledge Assistant — version 0.4.0

A private, offline question-answering assistant for emergency-management training
material. It answers questions from a curated corpus of FEMA and related documents
and cites the documents it used. Everything runs on the user's own Windows PC: the
language models, the database and the application. Questions and documents are
not sent anywhere.

Built at the University of Arkansas at Little Rock. Not licensed for redistribution
(`UNLICENSED`).

---

## Status of this version

**0.4.0 is built but not ready to distribute.** The code is complete and tested. The
remaining problems are in the release packaging and one bug:

| # | Issue | Effect | What it takes |
|---|---|---|---|
| 1 | **The installer is invalid.** `electron/dist/EM Knowledge Assistant-Setup-0.4.0.exe` is a 0.2 MB stub; its app package was left beside it as `emb-hybrid-desktop-0.4.0-x64.nsis.7z`. | It will not install the app. | Rebuild the installer on a machine where Defender's ASR rule `01443614…` does not block it (see *Code signing*), then check it is ~95 MB. |
| 2 | **Citation links fail on users' machines.** The shipped graph stores the build machine's absolute file paths. | Answers and citation names are fine; clicking a citation returns an error. | A small code fix, then rebuild. |
| 3 | **Unsigned.** 31 binaries carry no signature. | Managed Windows machines refuse to run them. | Signing, or an IT exclusion. See *Code signing*. |
| 4 | **Neo4j usage reporting is on by default.** | The database may periodically send anonymous usage statistics to Neo4j. No questions or documents are included. | One setting, then rebuild the Neo4j package. |

Items 1, 2 and 4 all need a rebuild, so they are best fixed together as 0.4.1,
before signing. Details and evidence are in
[`docs/DECONTAINERIZE_PLAN.md`](docs/DECONTAINERIZE_PLAN.md) under *Remaining*.

---

## What it is made of

| Component | Version | Role | Signed? |
|---|---|---|---|
| Desktop app (Electron) | Electron 43.1.0 | Window, first-run setup wizard, starts and stops the other parts | No |
| Application service (`emb-api.exe`) | Python 3.13, FastAPI, frozen with PyInstaller | Retrieval, prompts, chat API, serves the UI | Exe no; most bundled libraries yes |
| Graph database | Neo4j Community 2026.08.1 | Stores the documents, text chunks, their embeddings and extracted entities | Yes (Apache) |
| Java runtime | Eclipse Temurin JRE 21.0.12.1 | Runs Neo4j | Yes (Eclipse) |
| Model runtime | Ollama (installed separately) | Runs the language models on the local GPU/CPU | Vendor's own installer |
| Chat model | `gemma4:12b-it-qat` (~6.7 GB) | Writes the answers | — |
| Embedding model | `embeddinggemma` (~0.6 GB, 768-dim) | Turns text into vectors for search | — |
| Corpus | 130 files (93 PDF, 27 PPTX, 8 DOCX, 2 MD) | The source documents, as a prebuilt graph of 10,360 chunks | — |

---

## How it runs on a user's machine

Installation is from a USB drive. The end-user instructions are
[`docs/USB_README.txt`](docs/USB_README.txt) (copied onto the drive as `README.txt`).
Machine preparation for IT is [`docs/TARGET_MACHINE_PREP.md`](docs/TARGET_MACHINE_PREP.md).

**First run** (10–20 minutes, reading from the USB drive): detect the GPU → find
or install Ollama → build the two model variants → unpack Neo4j and Java → unpack
the application service → unpack the documents → load the prebuilt graph → start.
Every step can be safely repeated, so an interrupted setup resumes where it stopped.

**Every run after that:** start Neo4j, wait until it accepts connections, start the
application service, wait for its health check, then open the chat window.

**Where things live:** the app installs per-machine. Its data (documents, database,
logs) is under `%APPDATA%\EM Knowledge Assistant`. Logs are in its `logs\` folder:
`electron.log` for the desktop app and `api.log` for the service. At the default
level they contain ids, file names, timings and errors, but not question text.

---

## Network and data

- **Everything listens on `127.0.0.1` only:** the service on 8000, Neo4j on 7687
  (database) and 7474 (browser), Ollama on 11434. Nothing is reachable from the
  network.
- **Answering a question needs no internet.** Retrieval, the models and the
  documents are all local.
- **Internet is used only** to download Ollama and the models on a machine that
  wasn't prepared in advance, and by Neo4j's usage reporting (issue 4 above).
  There is no auto-update and no telemetry from the app itself.
- **Credentials:** each installation generates its own random database password on
  first run and stores it only on that machine. No password or key ships in the
  installer or the assets.
- **No login.** The service has no user accounts because it only accepts
  connections from the same machine. The one endpoint that serves files is
  restricted to the document folder.

Verified in a pre-submission audit on 2026-09-23:

- the build machine's database password appears in none of the 989 shipped files;
- no `.env`, key or credential files ship, and the graph dump contains no user
  accounts;
- all listeners are bound to `127.0.0.1`;
- the file endpoint refused all seven path-traversal attempts tried against it;
- the UI loads nothing from the internet;
- a live run answered a real question from the right documents.

---

## Code signing

The package contains **31 unsigned binaries**; everything else is already signed by
its vendor. The full list is in
[`docs/TARGET_MACHINE_PREP.md`](docs/TARGET_MACHINE_PREP.md#known-limitation-unsigned-binaries-are-blocked).
In summary:

- the installer;
- the desktop app's `.exe`, `elevate.exe` and 6 graphics/media DLLs;
- `emb-api.exe` and 21 Python extension libraries (`.dll`/`.pyd`) in its
  `_internal` folder.

On UALR-managed Windows, Microsoft Defender's Attack Surface Reduction rule
`01443614-CD74-433A-B99E-2ECDC07BFC25` ("block executable files unless they meet a
prevalence, age, or trusted list criterion") blocks these. It has been observed
blocking `emb-api.exe` at launch, and blocking the installer build itself (issue 1).
Microsoft describes the rule as covering DLLs as well as executables. Workable
routes:

- sign all 31 files with the UALR certificate and put the certificate on the
  organization's trusted list (a brand-new certificate can still fail the rule's
  prevalence test);
- or exclude the app's install folder, and the build machine's output folder, from
  this rule.

Signing is configured for publisher *University of Arkansas at Little Rock*
(`electron/package.json` → `win.signtoolOptions`). The build script's
`-CertSubject` option currently signs only `emb-api.exe` and will be extended to
the other 21 when the certificate is available.

---

## Other known limitations

- **Search needs a few seconds after startup.** The service rebuilds its search
  index on every start. For about 5 seconds after the window opens (longer on
  slower laptops), a question gets an answer without any sources.
- **Deprecation warning in `api.log`.** Neo4j 2026.08.1 marks the vector-search call
  the app uses as deprecated. It works, but logs a warning per question, and a
  future Neo4j version may remove it.
- **Windows only.** macOS build settings exist, but 0.4.0 was built only for
  Windows 10/11 64-bit, and has only been tested on Windows 11.

---

## Building from source

For maintainers. The full procedure is in [`CLAUDE.md`](CLAUDE.md) (*Common
Commands*); the developer setup is [`docs/NATIVE_DEV.md`](docs/NATIVE_DEV.md).

```powershell
# 1. Stage Neo4j Community + a JRE 21 zip (downloads not included)
pwsh -File scripts/stage-neo4j.ps1 -Zip <neo4j-community-2026.08.1-windows.zip> `
     -JreZip <temurin-jre-21.zip> -Dump .\release\neo4j.dump -ReExport

# 2. Build the five release assets and their checksums
pwsh -File electron/scripts/build-release.ps1 -Neo4jHome C:\stage\neo4j -JreHome C:\stage\jre `
     -Python "$env:USERPROFILE\.conda\envs\pyAI\python.exe"

# 3. Build the installer (needs a machine where the ASR rule doesn't block it; expect ~95 MB)
cd electron; npm install; npm run dist:win; cd ..

# 4. Assemble the USB drive
pwsh -File scripts/stage-usb.ps1 -Destination E:\ -Verify
```

Run steps 2–4 once each, in order. Re-running step 2 after step 3 changes the
checksums, and step 4 will refuse until step 3 is re-run.

**Tests:** `pytest` (143 passing) and `cd electron; npm test` (92 passing).

---

## Where to find things

| Path | What |
|---|---|
| `src/` | The application service (FastAPI): routers, retrieval, models, config |
| `pipeline/` | Building the graph: ingest → load manifest → enrich |
| `electron/` | Desktop app, setup wizard and build scripts ([`electron/README.md`](electron/README.md)) |
| `scripts/` | Staging, USB assembly, graph export/import, dev launcher |
| `release/` | Built release assets (not in git) |
| `docs/DECONTAINERIZE_PLAN.md` | Architecture, history, current status and every known pitfall |
| `docs/NATIVE_DEV.md` | Setting up a development machine |
| `docs/TARGET_MACHINE_PREP.md` | Preparing a user's machine, and the signing list |
| `docs/USB_README.txt` | End-user installation instructions |
| `docs/HYBRID_SETUP.md` | Ollama setup, GPU checks, sharing the graph |
| `docs/explainer/index.html` | Illustrated walkthrough of how the code works (open in a browser) |
