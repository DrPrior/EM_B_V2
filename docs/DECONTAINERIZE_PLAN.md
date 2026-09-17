# Decontainerization Plan

> **Status: CODE DONE — release artifacts remain.** The API, the dev/pipeline
> flow, the Electron shell and the build scripts all run native, with no
> container assumptions anywhere. What's left is not code: **stage a Community
> Neo4j + a redistributable JRE**, **settle the dump's store format**,
> **code-sign**, and **prove a first run on a clean machine**. This doc is the
> canonical source of truth; every other doc's "decontainerization" banner points
> here. Working branch: `Decontainerize`.

## Why

Docker is no longer permitted on the organization's (UALR) machines, so the app
must run with **no container runtime at all**. Neo4j and the FastAPI API — the
only two things that were in Docker — move to **native host processes**. Ollama
was always host-native.

## Target architecture

```
Electron shell (supervisor)
   ├─ spawns  Neo4j        (native server + bundled JRE)   ── bolt 127.0.0.1:7687
   ├─ spawns  FastAPI API  (frozen exe; uvicorn in dev)     ── http 127.0.0.1:8000
   └─ ensures Ollama       (native, already present)         ── http 127.0.0.1:11434
```

Everything is `127.0.0.1`. `host.docker.internal` is gone, which also removes the
`OLLAMA_HOST=0.0.0.0` LAN exposure and the entire firewall-hardening burden —
Ollama returns to binding loopback only.

## Progress

**Landed (on `Decontainerize`):**
- **A — app native-safety:** `DB_URI`/`DATA_ROOT` env-driven; POSIX-normalized
  `File.filepath`; `config` `extra="ignore"`; `_file_url` separator-robust; the
  `graph.py` syntax fix.
- **B — native dev stack:** `.env.example` native-first, `scripts/dev-up.ps1`,
  `docs/NATIVE_DEV.md`. Neo4j runs via Neo4j Desktop in dev.
- **Embedding swap:** `qwen3-embedding:4b` (2560-d) → `embeddinggemma:latest`
  (768-d); vector index + Modelfile + config + tests updated.
- **Parallel enrichment:** Pass 2 thread-pooled (`enrichment_concurrency`,
  default 4) — ~2.3× on the RTX 4000, ~10 h → ~4.5 h.
- **`cryptography` dependency** added (AES-encrypted PDFs were silently dropped).
- **API decontainerization finish:** admin endpoints default to `settings.data_root`;
  container references removed from docstrings; **`src/core/paths.py`** added with
  `sys.frozen`/`_MEIPASS`-aware `resource_root()`/`modelfile_path()`/`static_dir()`,
  and `ollama_bootstrap` + `main.py` now resolve Modelfiles and the static UI
  through it (frozen-ready). The Docker files (`Dockerfile*`, `docker-compose*.yml`)
  were deleted.
- Graph **rebuilt** on native Neo4j (`2026.07.x`): 10,360 chunks at 768-d, vector
  index `chunk_vector_idx` ONLINE.
- **D — Electron native stack:** `lib/docker.js` and `lib/compose.js` **deleted**;
  `lib/procs.js` spawns `neo4j console` (with the bundled JRE as `JAVA_HOME`) and
  `emb-api.exe`, with bolt/`/health` readiness probes and process-tree teardown;
  `supervisor.js`, `firstrun.js` (`gpu → ollama → models → neo4j → runtime → data
  → snapshot → start`), `snapshot.js` (native `neo4j-admin database load`),
  `envfile.js`, `paths.js` and the wizard step list all rewritten. `lib/apibundle.js`
  re-unpacks the API bundle when the shipped manifest is newer than what's
  installed. `OLLAMA_HOST=0.0.0.0` dropped from `ollamaenv.js`.
- **E — packaging:** `run_api.py` + `emb-api.spec` (one-dir, `unstructured` and the
  dev/notebook stack excluded — see below); `unstructured` dropped from
  `requirements.txt`; `build-release.ps1` rewritten native (PyInstaller + Neo4j/JRE
  zips + dump + corpus, SHA-256s into the manifest, optional `-CertSubject`);
  `assets.manifest.json` carries `apiBundle`/`neo4j`/`jre` instead of the image
  tar; the compose `extraResources` entry is gone from `package.json`;
  `stage-usb.ps1` + the end-user docs are native. The built bundle satisfies the
  `src/core/paths.py` resource contract (Modelfiles at the bundle root,
  `src/static` at its subpath) and carries every runtime module in its archive.
  **It has never been executed** — see the ASR blocker below.

**Remaining — artifacts and validation, not code:**

- **C inputs are not staged.** `build-release.ps1` needs `-Neo4jHome` and
  `-JreHome`, and neither exists yet. The dev box has only **Enterprise** DBMSs
  (`2026.03.1` / `2026.05.0` / `2026.07.1`) from Neo4j Desktop; the ship path needs
  **Community** of the matching line, plus a JRE you may redistribute (Adoptium or
  Azul direct — not the copy in Neo4j Desktop's cache).
- **The dump's store format is unverified.** The graph was built on Enterprise,
  whose default store is `block`, and Community refuses to load a block dump.
  `backup-block/neo4j.dump` (132 MB) and a newer `release/neo4j.dump` (47 MB) both
  exist from 2026-09-14, suggesting a migration ran, but nothing records the
  result. **Prove it by loading `release/neo4j.dump` into a fresh Community
  install before trusting it.**
- **⚠️ Defender ASR blocks the frozen exe outright — verified 2026-09-17 on the
  dev machine.** Launching `dist/emb-api/emb-api.exe` fails with `Access is
  denied.` and no Python traceback. The cause is in the Defender Operational log
  (event **1121**), not in AppLocker:

  ```text
  ID: 01443614-CD74-433A-B99E-2ECDC07BFC25
  Path: C:\Users\seprior\EM_B_Hybrid\dist\emb-api\emb-api.exe
  ```

  That GUID is the ASR rule **"Block executable files from running unless they
  meet a prevalence, age, or trusted list criterion"**, in **Block** mode under
  UALR's managed policy. It does not appear in `Get-MpPreference`'s
  `AttackSurfaceReductionRules_Ids` because it is set by policy CSP (Intune), so
  the machine looks clean until you try to run something.

  Consequences to plan around:
  - **A freshly built exe cannot be smoke-tested on a managed machine**, including
    this one. Ask IT for an ASR path exclusion (`Add-MpPreference
    -AttackSurfaceReductionOnlyExclusions`, admin) for the build output dir, or
    build/test on an unmanaged box or VM.
  - **Signing is necessary but may not be sufficient.** The rule's criteria are
    prevalence *or* age *or* trusted-list. A brand-new signed binary from a cert
    with no reputation can still fail prevalence. The dependable fix is the cert
    being on the org's trusted list / an ASR exclusion deployed with the app —
    settle this with IT *before* committing to the folder-copy delivery model.
  - Diagnose any future "Access is denied" with:
    `Get-WinEvent -LogName "Microsoft-Windows-Windows Defender/Operational" |
    Where-Object Id -eq 1121`.
- **Signing:** `win.signtoolOptions` has no `certificateSubjectName` and
  `build-release.ps1 -CertSubject` has never been used, so the exe and the
  installer both ship unsigned. Gated on the UALR certificate — and see the ASR
  item above, which raises the stakes: unsigned here means "does not run", not
  just "shows a warning".
- **No end-to-end run.** `procs.js`, `supervisor.js`, `firstrun.js`, `snapshot.js`
  and `archive.js` have **no unit tests** (only `apibundle`, `logger`, `ollamaenv`
  do). A clean-machine first run is the only thing that exercises them.

## How the runtimes ship

Fleet machines have **no Docker and IT blocks unsigned installers** — everything
shipped must be signed or installer-free.

- **Python API — PyInstaller one-dir → `emb-api.exe` + `_internal/`, code-signed
  with the UALR cert.** End users copy a folder, not run an installer.
  - **The biggest freeze risk is gone:** `unstructured` is declared in
    `requirements.txt` but **never imported** — the code parses with
    `pypdf` / `python-docx` / `python-pptx` (+ `cryptography`). Dropping
    `unstructured` removes the optional-parser/data-file freeze hazard; the
    remaining parsers freeze cleanly.
- **Neo4j — Community zip + bundled JRE**, unpacked (no admin service install).
  Supervisor runs `neo4j console` as a child.

## C. Bundle native Neo4j + JRE (the remaining workstream)

- Ship **Neo4j Community (unpacked zip) + a bundled JRE 17/21** under the app's
  resources; no admin installer. Neither is staged yet — `build-release.ps1`
  takes them as `-Neo4jHome` / `-JreHome`.
- **Store-format line = `2026.07.x`**, to match the dump. `neo4j-admin database
  load` refuses a store-format mismatch. (This supersedes the `2026.04.0` pin
  from the Docker era, now corrected everywhere.)
- **Community vs Enterprise is the sharp edge.** Dev runs Enterprise via Neo4j
  Desktop, and Enterprise defaults to the `block` store format, which **Community
  cannot load**. The dump you ship must be record/aligned. `backup-block/neo4j.dump`
  plus a newer, smaller `release/neo4j.dump` suggest a block→record migration
  already ran on 2026-09-14, but that was never verified or written down — load
  `release/neo4j.dump` into a fresh Community install and confirm before shipping.
- First-run order: `neo4j-admin dbms set-initial-password <random>` **before** the
  first start → `neo4j-admin database load` the dump (offline) → `neo4j console`.
  Password-before-init is mandatory or auth breaks (same trap the Docker volume had).
  This is what `lib/firstrun.js` + `lib/snapshot.js` already do.
- Config the zipped Neo4j home before staging it: bind bolt + http to `127.0.0.1`;
  data dir + modest heap/pagecache under the app's userData dir.
- JRE licensing: take it from Adoptium or Azul directly so it is yours to
  redistribute — not the copy sitting in Neo4j Desktop's cache.

## D / E as built

Both landed; see **Progress** above for the file-by-file summary. The parts worth
remembering when touching them:

- **Process lifecycle is yours now.** Docker gave restart policies,
  `depends_on: service_healthy` ordering, and clean teardown for free. `lib/procs.js`
  owns startup ordering (Neo4j ready before API), crash detection, orphan cleanup on
  relaunch, and port-in-use collisions, using real readiness probes (bolt connect +
  `/health`, not just process-alive).
- **The asset contract is positional.** Each zip must unpack with its contents at
  the **root**, landing at `<userData>/api`, `<userData>/neo4j`, `<userData>/jre`.
  `build-release.ps1`'s `Compress-Contents`, `lib/firstrun.js` and `lib/paths.js`
  all encode that; break one and first run fails late, after a multi-GB copy.
- **The manifest is the version handshake.** `stage-usb.ps1` refuses to stage if
  the installer's baked-in `assets.manifest.json` differs from the repo's, which is
  what catches "assets rebuilt but installer not". So the order is always
  `build-release.ps1` → `npm run dist:win` → `stage-usb.ps1`.
- **The freeze needs a curated env.** `emb-api.spec` keeps an `EXCLUDES` list
  because `python-pptx → PIL` references IPython (under `TYPE_CHECKING` and a
  `try/except ImportError`) and Tk, and PyInstaller's pydantic hook collects
  `pydantic.mypy`, which drags in mypy. Unexcluded, a maintainer's dev env leaked
  ~35 MB of notebook/type-checker stack into the shipped bundle (154 MB → 119 MB).
  Build from the env that holds the runtime deps, not a bare system Python.

## Top pitfalls (consolidated)

1. **Neo4j store-format lock** — bundle `2026.07.x`, and make sure the dump is
   record/aligned (Community-loadable), not Enterprise `block`.
2. **Neo4j password before first init**, then load.
3. **IT's unsigned-installer block** — sign the API exe *and* the installer;
   gated on the UALR cert being staged.
4. **Process supervision** you now own (ordering, readiness, restart, teardown,
   orphans, ports).
5. **Bundle a JRE** — don't assume host Java.
6. **Don't re-download/re-execute runtimes** on pre-provisioned machines
   (endpoint-security dropper pattern) — use in place, verify by hash.
7. **Size** — API bundle + Neo4j + JRE + models + corpus grows the installer/USB.
8. **Defender ASR blocks unsigned/low-prevalence exes** (rule
   `01443614-CD74-433A-B99E-2ECDC07BFC25`, Block mode) — it stops `emb-api.exe`
   from running at all, with a bare `Access is denied.` and nothing in AppLocker.
   See the Remaining section for the evidence and the ways out.
9. **Keep dev tooling out of the freeze.** PyInstaller follows optional and
   plugin imports, so a maintainer's env leaks into the artifact (`python-pptx →
   PIL → IPython/Tk`, `pydantic.mypy → mypy`). `emb-api.spec`'s `EXCLUDES` is the
   guard; re-check the bundle's top-level dirs after adding a dependency.

(`unstructured` freeze risk — retired: the dep is unused and now dropped.)

## Suggested sequencing

1. ~~**Packaging spike:** drop `unstructured`; write `run_api.py` + the
   PyInstaller spec.~~ Done — but "prove the frozen exe serves the UI and ingests
   PDF/PPTX/DOCX" is **still open**, blocked by the ASR rule above. Resolve that
   first: it gates every later validation step, and a signing cert that doesn't
   clear the rule invalidates the delivery model.
2. **Bundle Neo4j + JRE**: stage a Community `2026.07.x` home + a redistributable
   JRE, set the password, load the dump, start it by hand — and confirm the dump
   is record/aligned rather than Enterprise `block`.
3. ~~**Electron rewrite**~~ and ~~**build pipeline**~~ — done; see **Progress**.
4. **Sign** the API exe and the installer once the UALR cert exists; re-check
   against the ASR rule.
5. **Clean-machine first-run test** — the only coverage `procs`/`supervisor`/
   `firstrun`/`snapshot` have.
