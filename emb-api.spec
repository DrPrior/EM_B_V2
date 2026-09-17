# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the native EM_B_Hybrid API (one-dir).

    pyinstaller emb-api.spec --noconfirm      # -> dist/emb-api/emb-api.exe (+ _internal/)

Bundles the runtime resources src/core/paths.py resolves under sys._MEIPASS:
- Modelfile / Modelfile.embeddings at the bundle root (modelfile_path)
- src/static preserving its subpath (static_dir)
Keep the `datas` list in sync with src/core/paths.py.

`unstructured` is excluded on purpose — it is not imported (the code uses pypdf /
python-docx / python-pptx + cryptography); excluding it keeps the bundle lean.
See EXCLUDES below for the rest of what is deliberately left out.
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("Modelfile", "."),
    ("Modelfile.embeddings", "."),
    ("src/static", "src/static"),
]

# Packages the app never imports, kept out so a maintainer's dev/notebook
# environment can't leak into the shipped bundle.
#
# The interactive stack is dragged in by one chain: python-pptx -> PIL, and
# PIL.Image / PIL.ImageShow reference IPython under `if TYPE_CHECKING` and a
# `try: from IPython.display import display / except ImportError: pass`. Neither
# runs at import time, so dropping IPython is safe — and it takes jedi, black
# (IPython's autoformatter) and matplotlib_inline -> matplotlib with it. PIL's Tk
# viewer likewise pulls tkinter plus the _tcl_data/_tk_data trees. Measured: that
# set alone was ~32 MB, and mypy (below) another ~3 MB — 154 MB -> 119 MB total.
#
# PIL, lxml and numpy are NOT excluded: python-pptx and python-docx need them.
EXCLUDES = [
    "unstructured",
    # interactive/notebook stack (reached only through PIL's optional hooks)
    "IPython",
    "ipykernel",
    "jupyter_client",
    "comm",
    "matplotlib",
    "matplotlib_inline",
    "jedi",
    "black",
    # PIL's Tk image viewer
    "tkinter",
    "PIL.ImageTk",
    # dev-only tooling that must never ship. mypy arrives via pydantic's bundled
    # mypy *plugin* (pydantic.mypy / pydantic.v1.mypy), which PyInstaller's
    # pydantic hook collects wholesale; the plugin is only ever imported by mypy
    # itself. Dropping it also drops mypy's 2.4 MB compiled ast_serialize.pyd.
    "mypy",
    "ast_serialize",
    "pydantic.mypy",
    "pydantic.v1.mypy",
    "pytest",
    "ruff",
]

# uvicorn resolves its loop/protocol/logging implementations by dynamic import,
# which static analysis misses; pull them all in. The document parsers are
# imported lazily inside functions, so name them explicitly to be safe.
hiddenimports = collect_submodules("uvicorn") + [
    "pypdf",
    "docx",
    "pptx",
    "cryptography",
    "slowapi",
]

a = Analysis(
    ["run_api.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="emb-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="emb-api",
)
