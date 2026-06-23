"""Unit tests for the source-file serving router."""

import pytest
from fastapi.testclient import TestClient

from src.core.config import settings
from src.main import app

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the data root at a temp dir with a known file, so file serving is
    # exercised without depending on the ingested corpus.
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "doc one.txt").write_text("hello source", encoding="utf-8")
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    yield TestClient(app)


def test_serves_existing_file(client: TestClient) -> None:
    resp = client.get("/files/sub/doc%20one.txt")

    assert resp.status_code == 200
    assert resp.text == "hello source"


def test_missing_file_returns_404(client: TestClient) -> None:
    resp = client.get("/files/sub/nope.txt")

    assert resp.status_code == 404


def test_path_traversal_blocked(client: TestClient) -> None:
    # Escaping the data root must not leak host files.
    resp = client.get("/files/../../../etc/passwd")

    assert resp.status_code in (403, 404)
