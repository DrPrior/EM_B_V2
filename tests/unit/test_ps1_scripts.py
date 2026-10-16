"""Unit tests that keep every ``.ps1`` script runnable under Windows PowerShell 5.1.

UALR machines ship only ``powershell.exe`` 5.1, which reads a BOM-less script as
the ANSI code page (cp1252), not UTF-8. An em dash (UTF-8 ``E2 80 94``) then
decodes as ``â€”``, and byte ``0x94`` is a curly quote that PowerShell treats as
a string delimiter, so strings end early and the script fails to parse. Keeping
the scripts pure ASCII avoids that regardless of what an editor does with BOMs.
The parse test also catches pwsh-7-only syntax such as ``??``.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", "dist", "release", ".claude"}


def _ps1_files() -> list[Path]:
    """Return every .ps1 script in the repo, outside build output and worktrees."""
    return sorted(
        p
        for p in REPO_ROOT.rglob("*.ps1")
        if not SKIP_DIRS.intersection(p.relative_to(REPO_ROOT).parts)
    )


def test_ps1_files_found() -> None:
    """Guard against the glob silently matching nothing."""
    assert _ps1_files()


@pytest.mark.parametrize(
    "script", _ps1_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_ps1_is_ascii(script: Path) -> None:
    """Every byte must be ASCII so PS 5.1's cp1252 decoding can't corrupt it."""
    offenders = [
        (lineno, line.decode("utf-8", errors="replace").strip())
        for lineno, line in enumerate(script.read_bytes().splitlines(), start=1)
        if any(b > 127 for b in line)
    ]
    assert not offenders, f"non-ASCII characters in {script.name}: {offenders}"


@pytest.mark.skipif(
    shutil.which("powershell.exe") is None, reason="Windows PowerShell not available"
)
def test_ps1_parses_under_windows_powershell() -> None:
    """Parse each script with powershell.exe (5.1) and expect zero errors."""
    command = (
        "$bad = 0; foreach ($f in ($env:PS1_FILES -split [char]10)) { "
        "$t = $null; $e = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        "$f, [ref]$t, [ref]$e); foreach ($x in $e) { $bad++; "
        "Write-Output ($f + ':' + $x.Extent.StartLineNumber + ' ' + $x.Message) } }; "
        "exit $bad"
    )
    # Paths go through the environment, not argv: -Command splices its trailing
    # arguments into the command text, which breaks on paths with spaces.
    files = "\n".join(str(p) for p in _ps1_files())
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env={**os.environ, "PS1_FILES": files},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
