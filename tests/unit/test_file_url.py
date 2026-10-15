"""Unit tests for ``_file_url``: turning a stored File.filepath into a citation link.

The case that matters most is a graph built on one machine and served on another.
``File.filepath`` is stored absolute, so the shipped graph carries the
maintainer's paths (``C:/Users/<maintainer>/.../project_data/...``), while an end
user's ``DATA_ROOT`` is ``<userData>/project_data``. Release 0.4.0 shipped with
every citation link broken for exactly that reason. The last test drives the
real ``/files`` router to prove the link actually opens the file.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.config import settings
from src.routers import files
from src.services.rag import _file_url

pytestmark = pytest.mark.unit

MAINTAINER = "C:/Users/seprior/EM_B_Hybrid/project_data"
USER_ROOT = "C:/Users/someone/AppData/Roaming/EM Knowledge Assistant/project_data"


@pytest.fixture
def data_root(monkeypatch):
    """Point settings.data_root at a given root for the duration of a test."""

    def _set(root: str) -> None:
        monkeypatch.setattr(settings, "data_root", root)

    return _set


# --- same machine: the behaviour that already worked ------------------------


def test_path_under_data_root_is_made_relative(data_root):
    data_root(MAINTAINER)
    assert _file_url(f"{MAINTAINER}/FEMA/NIMS.pdf") == "/files/FEMA/NIMS.pdf"


def test_spaces_and_special_characters_are_url_encoded(data_root):
    data_root(MAINTAINER)
    url = _file_url(f"{MAINTAINER}/FEMA Material/IS-200 & more.pptx")
    assert url == "/files/FEMA%20Material/IS-200%20%26%20more.pptx"


def test_empty_or_missing_filepath_gives_no_link(data_root):
    data_root(MAINTAINER)
    assert _file_url(None) is None
    assert _file_url("") is None


# --- graph built on another machine: the 0.4.0 bug ---------------------------


def test_maintainer_path_maps_onto_the_users_corpus(data_root):
    data_root(USER_ROOT)
    url = _file_url(f"{MAINTAINER}/FEMA Material/Visuals/Lesson1.pptx")
    assert url == "/files/FEMA%20Material/Visuals/Lesson1.pptx"


def test_the_link_never_carries_the_other_machines_path(data_root):
    data_root(USER_ROOT)
    url = _file_url(f"{MAINTAINER}/FEMA/NIMS.pdf")
    assert "seprior" not in url
    assert "Users" not in url


def test_windows_backslash_paths_from_another_machine_map_too(data_root):
    data_root(USER_ROOT)
    stored = MAINTAINER.replace("/", "\\") + "\\FEMA\\NIMS.pdf"
    assert _file_url(stored) == "/files/FEMA/NIMS.pdf"


def test_corpus_folder_match_ignores_case(data_root):
    data_root(USER_ROOT)
    assert _file_url("D:/Build/Project_Data/FEMA/NIMS.pdf") == "/files/FEMA/NIMS.pdf"


def test_the_outermost_corpus_folder_is_the_root(data_root):
    # A content folder that happens to share the corpus folder's name must not
    # be mistaken for the root.
    data_root(USER_ROOT)
    url = _file_url(f"{MAINTAINER}/Archive/project_data/notes.md")
    assert url == "/files/Archive/project_data/notes.md"


def test_container_era_paths_still_map(data_root):
    data_root(USER_ROOT)
    assert _file_url("/app/project_data/FEMA/NIMS.pdf") == "/files/FEMA/NIMS.pdf"


def test_a_data_root_with_a_different_folder_name_is_honoured(data_root):
    data_root("E:/corpus")
    assert _file_url("C:/elsewhere/corpus/FEMA/NIMS.pdf") == "/files/FEMA/NIMS.pdf"


def test_an_unplaceable_absolute_path_gives_no_link(data_root):
    # No corpus folder anywhere in it: a link would be refused by /files and
    # would expose the other machine's layout, so give none. The UI then shows
    # the source name without a link.
    data_root(USER_ROOT)
    assert _file_url("C:/Users/seprior/Desktop/stray.pdf") is None
    assert _file_url("/home/someone/stray.pdf") is None


def test_an_already_relative_path_is_kept(data_root):
    data_root(USER_ROOT)
    assert _file_url("FEMA Material/NIMS.pdf") == "/files/FEMA%20Material/NIMS.pdf"


# --- end to end: the link has to actually open the file ----------------------


def test_link_for_a_maintainer_path_opens_the_file_on_a_users_machine(
    tmp_path: Path, data_root
):
    user_root = tmp_path / "EM Knowledge Assistant" / "project_data"
    doc = user_root / "FEMA Material" / "Visuals" / "Lesson1.pptx"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"slides")
    data_root(user_root.as_posix())

    url = _file_url(f"{MAINTAINER}/FEMA Material/Visuals/Lesson1.pptx")

    app = FastAPI()
    app.include_router(files.router)
    response = TestClient(app).get(url)
    assert response.status_code == 200
    assert response.content == b"slides"
