"""Unit tests for src.core.paths (from-source resolution)."""

import pytest

from src.core import paths

pytestmark = pytest.mark.unit


def test_resource_root_is_repo_root() -> None:
    root = paths.resource_root()
    # From source this is the repo root: it holds src/ and the Modelfiles.
    assert (root / "src").is_dir()
    assert (root / "Modelfile").is_file()
    assert (root / "Modelfile.embeddings").is_file()


def test_modelfile_path_resolves_to_existing_files() -> None:
    assert paths.modelfile_path("Modelfile").is_file()
    assert paths.modelfile_path("Modelfile.embeddings").is_file()


def test_static_dir_exists_and_serves_ui() -> None:
    static = paths.static_dir()
    assert static.is_dir()
    assert (static / "index.html").is_file()
