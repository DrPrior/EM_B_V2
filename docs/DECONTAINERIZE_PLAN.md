# Decontainerization Plan

> **Status: 0.4.0 BUILT BUT NOT DISTRIBUTABLE — rebuild as 0.4.1, sign, prove.**
> The API, the dev/pipeline flow, the Electron shell and the build scripts all run
> native. Community 2026.08.1 + Temurin JRE 21 are staged, and the shipped dump is
> verified to load and serve on that exact server. 0.4.0 was built on 2026-09-18,
> and a docs check on 2026-09-23 found three problems (see Remaining). Its
> **installer is an invalid stub**, because the ASR rule blocked the build. The
> **citation-link bug** and **Neo4j usage reporting** are fixed in code but not
> yet in a build. What's left: **rebuild as 0.4.1** on a machine the ASR rule
> doesn't block, **code-sign** (UALR cert + ASR rule; 31 binaries), and **prove
> a first run on a clean machine**. This doc is the canonical source of truth;
> every other doc's "decontainerization" banner points here. Working branch:
> `Decontainerize`.

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
- Graph **rebuilt** on native Neo4j (`2026.07.x`, dev since upgraded to 2026.08.1): 10,360 chunks at 768-d, vector
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

- ~~C inputs are not staged.~~ **Done 2026-09-18** — see *C. as built* below.
  Neo4j Community **2026.08.1** at `C:\stage\neo4j`, Temurin **JRE 21.0.12.1** at
  `C:\stage\jre`, both produced by `scripts/stage-neo4j.ps1`.
- ~~Run the release build.~~ **Done 2026-09-18** (0.4.0; checksums committed in
  #36). The order is `build-release.ps1 -Neo4jHome C:\stage\neo4j -JreHome
  C:\stage\jre -Python <pyAI>\python.exe`, then `npm run dist:win`, then
  `stage-usb.ps1 -Verify`, **each exactly once and in that order**. Re-running
  build-release after the installer regenerates the checksums (build timestamps
  change them), and stage-usb then refuses; it now names the cause and the fix.
- **Pre-submission audit, 2026-09-23 — passed** (Python 156 after the
  citation-link fix, 143 at audit time) / Electron 92 tests;
  ruff check clean. The frozen bundle is built from committed code (every freeze
  input predates the build; bundled resources byte-identical to HEAD). The dev
  Neo4j password is found in none of the 989 shipped files; no `.env`, keys or
  credential files ship, and the dump carries only the `neo4j` database (no users).
  API and Neo4j bind `127.0.0.1` only; the legacy `api_server.py` (`0.0.0.0`) is
  not frozen in; the UI loads nothing external. `/files` refused all 7 traversal
  probes. A live run from source answered a real question with correct citations,
  and streaming and graph search both work. Two follow-ups surfaced (below, not
  blockers).
- ~~The dump's store format is unverified.~~ **Settled 2026-09-17:
  `release/neo4j.dump` is `record-aligned-1.1` — Community-loadable.** The
  2026-09-14 block→record migration did happen and `release/neo4j.dump` is its
  output; `backup-block/neo4j.dump` is the pre-migration original
  (`block-block-1.1`, Enterprise-only). The live dev store is record format too
  (35 store files, the classic `neostore.*` layout), which is why a dump taken
  from it is loadable by Community despite Neo4j Desktop being Enterprise.

  How it was checked, without a Community install and without stopping the
  running database — load into a scratch data dir, then read the format:

  ```powershell
  $env:JAVA_HOME = "<Neo4jDesktop2>\Cache\runtime\zulu21...-jre21..."
  $admin = "<Neo4jDesktop2>\Cache\dbmss\neo4j-enterprise-2026.08.1\bin\neo4j-admin.bat"  # or C:\stage\neo4j\bin
  # scratch.conf sets server.directories.data + .transaction.logs.root to a temp dir
  & $admin database load --from-path=<repo>\release --additional-config=scratch.conf neo4j
  & $admin database info --from-path=<temp>\data\databases neo4j
  ```

  `database load --info` alone is not enough — it reports the *archive* format
  ("Neo4j ZSTD Dump"), never the store format. Re-verify this way after any
  re-export, because the check is cheap and a mismatch only surfaces on the
  user's machine.
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
  just "shows a warning". **The 2026-09-23 audit found 31 unsigned binaries**:
  the installer; the desktop app's exe, `elevate.exe` and 6 DLLs; `emb-api.exe`;
  and **21 `.dll`/`.pyd` under `_internal\`**. Everything else is vendor-signed
  (JRE by Eclipse, Neo4j by Apache, most of the Python runtime by
  Anaconda/Microsoft). The full list is in `TARGET_MACHINE_PREP.md`. Two gaps to
  close once the cert exists:
  - `-CertSubject` signs **only `emb-api.exe`**. Microsoft describes the ASR rule
    as covering `.dll` too, so it must also sign the 21 `_internal` binaries.
  - electron-builder signs the app exe and installer; confirm it also signs the
    bundled DLLs, or add it to the signing config.
- **⚠️ The 0.4.0 installer in `electron/dist/` is invalid — do not distribute it.**
  Found 2026-09-23. `EM Knowledge Assistant-Setup-0.4.0.exe` is **0.2 MB**
  (0.3.1 was 95 MB), and the app package it should contain was left beside it as
  `emb-hybrid-desktop-0.4.0-x64.nsis.7z` (94.3 MB), with no `.blockmap`. Cause,
  from the Defender Operational log: at **15:43:35 on 2026-09-18**, the second
  the installer was written, ASR rule `01443614…` (event 1121) blocked `node.exe`
  (electron-builder) from **executing** that exe. On Windows, electron-builder
  runs a freshly compiled installer during the NSIS build to produce the
  uninstaller. On a machine enforcing this rule, that step is blocked and the
  build stops partway. So **the installer cannot be built correctly on this
  machine as it is**, even though the unpacked app (`win-unpacked/`, 347 MB) and
  all five release assets are fine. The fix is an ASR exclusion for the build
  output folder, or building on an unmanaged machine or VM. Then re-run `npm run
  dist:win` and check the result is ~95 MB with a `.blockmap` before staging.
  `stage-usb.ps1` does not currently check installer size.
- **⚠️ Known bug in 0.4.0: citation links fail on every end-user machine.**
  Found 2026-09-23 while checking the docs; the audit's live run missed it
  because it ran with the maintainer's own `DATA_ROOT`. The shipped graph stores
  every `File.filepath` as an absolute maintainer path
  (`C:/Users/seprior/EM_B_Hybrid/project_data/...`, 147/147). `_file_url`
  (`src/services/rag.py`) turns a filepath into a link by stripping `DATA_ROOT`
  as a prefix. On a user's machine `DATA_ROOT` is
  `<userData>/project_data` (`electron/lib/envfile.js`), the prefix doesn't
  match, and the link keeps the full path:
  `/files/C%3A/Users/seprior/.../x.pdf`, which the traversal guard refuses (403).
  The file itself is present, and `/files/<relative path>` serves it (200).
  Reproduced with the real `_file_url` and `/files` router against a simulated
  user `DATA_ROOT`. Answers and citation *names* are unaffected; clicking through
  to the source is broken, and each link leaks the maintainer's Windows username.
  **Fixed in code 2026-09-23; takes effect at the next build** (the 0.4.0
  `emb-api.zip` in `release/` still has the old code). When the `DATA_ROOT`
  prefix doesn't match, `_file_url` now falls back to `_relative_to_corpus`:
  keep whatever follows the outermost corpus folder (`project_data`, or
  `DATA_ROOT`'s own folder name), matched case-insensitively. It returns *no*
  link, rather than a broken one, for an absolute path it can't place, and the
  UI then shows the source name unlinked. `tests/unit/test_file_url.py` (13
  tests) covers it, including an end-to-end test that opens a maintainer-path
  citation through the real `/files` router under a user-style `DATA_ROOT`.
  Nine of those tests fail against the 0.4.0 code. The data-side alternative
  (store `File.filepath` relative to the corpus root at ingest) is still
  cleaner long-term, but it would touch ingestion, the router and every
  existing graph.
- **Neo4j usage reporting is on in the 0.4.0 server.** Neo4j defaults
  `dbms.usage_report.enabled=true` (and `client.allow_telemetry=true`, for
  Neo4j Browser). The 0.4.0 staged Community `neo4j.conf` only carried the
  setting commented out, so 0.4.0's Neo4j would periodically try to send
  anonymous usage statistics to Neo4j over the internet. That's no questions or
  documents, but it is outbound traffic a reviewer will see. None was observed
  during a spot check of the dev server on 2026-09-23; the reports are periodic.
  **Fixed 2026-09-23; takes effect at the next build:** `stage-neo4j.ps1` now
  sets both to `false`. They have been applied to `C:\stage\neo4j`, and
  `neo4j-admin server validate-config` accepts them. A control with a bogus
  setting is rejected, so Community 2026.08.1 does recognise both names.
  `neo4j-community.zip` in `release/` still has the old config until
  `build-release.ps1` re-zips it.
- **Follow-ups from the audit (not blockers):**
  - *Index rebuild after `/health`.* Every API start drops and rebuilds
    `chunk_vector_idx`; measured ~5 s where `/health` is green but vector search
    returns nothing, longer on slow laptops. Either keep the index when its
    dimensions match, or make `/health` (or the supervisor) wait for `ONLINE`.
  - *Deprecated vector procedure.* Neo4j 2026.08.1 flags
    `db.index.vector.queryNodes` as deprecated in favour of the Cypher `SEARCH`
    clause. It works, but logs a long warning per chat into `api.log`, and a
    future Neo4j may remove it.
  - *Formatting.* `ruff format` would restyle `pipeline/load_manifest.py` and six
    test files. Style only; do it after signing, because any change to shipped
    Python means a rebuild.
- **No end-to-end run.** Unit coverage now reaches the decidable parts —
  `procs` (readiness probes), `archive` (the contents-at-root contract, against
  the real OS `tar`), `envfile` (password stability) and `snapshot` (the
  import-once marker and load→migrate), alongside `apibundle`, `logger` and
  `ollamaenv`: 92 tests.
  What unit tests cannot reach is still the risky part: **`supervisor.js` and
  `firstrun.js` are only exercised by a real first run** — startup ordering,
  crash detection, orphan cleanup, port collisions, and the multi-GB unpack.
  That run is blocked on the ASR rule above. (The Neo4j half of first run —
  password → load → migrate → start — has been exercised by hand against the
  staged server; see *C. as built*.)

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

## C. as built (Neo4j + JRE)

**What ships:** Neo4j **Community 2026.08.1** (unpacked zip) + Temurin **JRE
21.0.12.1** (zip, not installer), staged at `C:\stage\neo4j` / `C:\stage\jre` by
`scripts/stage-neo4j.ps1`. `release/neo4j.dump` is at that server's formats.

**How we got there, and what each step taught us:**

- **Finding the download.** The Neo4j Deployment Center lists only the newest
  release, so older lines look gone. They aren't: `dist.neo4j.org` serves them
  by direct URL (`neo4j-community-<ver>-windows.zip` + `.sha256`). We chose the
  then-current 2026.08.1 over the dump's original 2026.07.1, since a two-month-old
  database server is an easy objection in an IT review.
- **The JRE.** Neo4j 2026.x is built and tested on Java 17/21: Neo4j Desktop
  bundles only those, and the dev server logs Azul Zulu 21. A JDK 25 `.msi` was
  the first download, and it failed on two counts, installer and version.
  `stage-neo4j.ps1` now rejects installers and checks `java -version`. The
  stable URL for the right artifact is
  `https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse`
  (~47 MB; a JDK would be ~180 MB).
- **Keeping the zipped home clean.** `dbms set-initial-password` **ignores
  `--additional-config`** and always writes `<NEO4J_HOME>\data\dbms\auth.ini`.
  Pointed at the home that gets zipped, that would ship a credential to every
  user, plus ~140 MB of graph duplicating `neo4j.dump`. So the script runs
  load/migrate/re-export in a scratch data dir, which *those* commands honour.
  It has no `-Password`, and it empties `data\` at the end. `build-release.ps1`
  refuses to zip a home carrying `auth.ini` or a populated store. Expect empty
  `data\transactions\` leftovers even from scratch-redirected commands; the
  guard allows them.
- **Migration, in three layers, all verified on the staged Community server:**
  1. *Store format:* `record-aligned-1.1` in both 2026.07 and 2026.08, so
     `migrate` was a no-op ("current store version and the migration target
     version are the same"). It's safe to run unconditionally, which is why
     `snapshot.js` does.
  2. *Database kernel version:* separate from the format. The re-exported dump
     starts on `V2026_08` under 2026.08.1.
  3. *Data:* 10,360 chunks (768-d), 147 files, 50,581 entities, 14 constraints,
     `chunk_vector_idx` ONLINE 100% with a working similarity query, no
     recovery pending, bound to `127.0.0.1` only.
- **Community vs Enterprise stays the sharp edge.** Dev runs Enterprise, which
  defaults *new* databases to `block`, a format Community cannot load.
  Existing stores keep their format through upgrades (verified below), but
  re-verify any re-export with the scratch-load check above. A dump taken from a
  block store produces an artifact that won't load, and nothing warns you.

**Dev was upgraded to match (2026-09-18):** Neo4j Desktop's in-place Upgrade
took the dev DBMS from Enterprise 2026.07.1 to **2026.08.1**. It kept
`record-aligned-1.1` and every transaction (31,582). One trap: on first start
Enterprise's `SystemGraphAutoUpgrader` moves the **system** database's kernel to
`V2026_08` straight away, but a **user** database stays on the old kernel
(`V2026_07`) **until its first write transaction**. Reads never trigger it, so
a read-only verification looks done when it isn't. Trigger it with a net-zero
write (`CREATE (n:__Probe) WITH n DELETE n`) and confirm `Upgrade transaction
from … to … completed` for `neo4j` in `debug.log`. The pre-upgrade backup is
`backup-dev-2026.07.1/` (`neo4j.dump` + `system.dump`).

**Rules that still apply when you touch any of this:**

- First-run order: `neo4j-admin dbms set-initial-password <random>` **before** the
  first start → `neo4j-admin database load` the dump (offline) → `database migrate`
  → `neo4j console`. Password-before-init is mandatory or auth breaks (same trap
  the Docker volume had). This is what `lib/firstrun.js` + `lib/snapshot.js` do,
  and it was exercised by hand against the staged server.
- **Ship a dump that is already at the bundled server's format version.**
  `lib/snapshot.js`'s `migrate` is a non-fatal backstop, not something to rely
  on. When the bundled Neo4j changes release, regenerate the shipped dump with
  `stage-neo4j.ps1 -Dump .\release\neo4j.dump -ReExport` (load → migrate →
  re-dump → verify the **re-exported** file; the original is kept as
  `neo4j.dump.pre-migration`).
- Re-stage with `scripts/stage-neo4j.ps1` rather than editing `C:\stage` by
  hand. It applies the loopback binds and 1g heap / 512m page cache, and leaves
  `data\` empty.
- JRE licensing: take it from Adoptium or Azul directly so it is yours to
  redistribute, not the copy sitting in Neo4j Desktop's cache.

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

1. **Neo4j store-format lock** — the bundled server is `2026.08.1`; make sure the dump is
   record/aligned (Community-loadable), not Enterprise `block`. The current
   `release/neo4j.dump` is verified `record-aligned-1.1`; re-check after any
   re-export.
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
10. **Freeze from the right Python.** A Python with PyInstaller but without the
    app's deps freezes "successfully" into a bundle that dies on launch, because
    PyInstaller only warns about unresolvable imports. `build-release.ps1`'s
    step 0 imports `src.main` to refuse that.
11. **`set-initial-password` ignores `--additional-config`.** It writes
    `auth.ini` into whichever Neo4j home owns the `neo4j-admin` you run. Never
    run it against a home that will be zipped, or against a shared Neo4j Desktop
    cache distribution.
12. **An upgraded user database finishes its kernel upgrade on first write.**
    After a Neo4j upgrade, read-only checks can pass while the database is
    still on the old kernel version. See *C. as built*.

(`unstructured` freeze risk — retired: the dep is unused and now dropped.)

## Suggested sequencing

1. ~~**Packaging spike:** drop `unstructured`; write `run_api.py` + the
   PyInstaller spec.~~ Done — but "prove the frozen exe serves the UI and ingests
   PDF/PPTX/DOCX" is **still open**, blocked by the ASR rule above. Resolve that
   first: it gates every later validation step, and a signing cert that doesn't
   clear the rule invalidates the delivery model.
2. ~~**Bundle Neo4j + JRE**~~ — done 2026-09-18: Community 2026.08.1 + JRE 21
   staged, dump re-exported, and the full first-run Neo4j sequence proven by
   hand against it. Dev upgraded to 2026.08.1 to match.
3. ~~**Electron rewrite**~~ and ~~**build pipeline**~~ — done; see **Progress**.
4. ~~**Run the release build**~~ — done 2026-09-18 (0.4.0), audited 2026-09-23.
5. **Sign** the API exe and the installer once the UALR cert exists; re-check
   against the ASR rule.
6. **Clean-machine first-run test** — the only coverage `supervisor.js` and
   `firstrun.js` have (the decidable parts of `procs`, `archive`, `envfile` and
   `snapshot` are unit-tested now).
