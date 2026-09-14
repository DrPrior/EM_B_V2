# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the native EM_B_Hybrid API (one-dir).

    pyinstaller emb-api.spec --noconfirm      # -> dist/emb-api/emb-api.exe (+ _internal/)

Bundles the runtime resources src/core/paths.py resolves under sys._MEIPASS:
- Modelfile / Modelfile.embeddings at the bundle root (modelfile_path)
- src/static preserving its subpath (static_dir)
Keep the `datas` list in sync with src/core/paths.py.

`unstructured` is excluded on purpose — it is not imported (the code uses pypdf /
python-docx / python-pptx + cryptography); excluding it keeps the bundle lean.
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("Modelfile", "."),
    ("Modelfile.embeddings", "."),
    ("src/static", "src/static"),
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
    excludes=["unstructured"],
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
