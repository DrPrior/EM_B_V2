"""Unit tests for LLM-based entity extraction (Ollama mocked)."""

from unittest.mock import patch

import pytest

from pipeline.extract import _parse_json, extract_entities, extract_material_type

pytestmark = pytest.mark.unit


# --- _parse_json ---------------------------------------------------------


def test_parse_json_plain_object() -> None:
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_strips_markdown_fences() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert _parse_json(raw) == {"a": 1}


def test_parse_json_extracts_object_from_surrounding_text() -> None:
    raw = 'Here you go: {"a": 1} hope that helps'
    assert _parse_json(raw) == {"a": 1}


def test_parse_json_no_object_returns_empty() -> None:
    assert _parse_json("no json here") == {}


def test_parse_json_malformed_returns_empty() -> None:
    assert _parse_json('{"a": }') == {}


# --- extract_entities ----------------------------------------------------


def test_extract_entities_parses_and_cleans() -> None:
    raw = (
        '{"concepts": ["  ICS ", "", 5], '
        '"organizations": [{"name": " FEMA ", "type": "agency"}, '
        '{"type": "no name"}], '
        '"legal_references": ["AR 525-13", "  "], '
        '"courses": ["IS-100"]}'
    )
    with patch("pipeline.extract.generate_response", return_value=raw):
        result = extract_entities("some text")

    assert result["concepts"] == ["ICS"]  # blank + non-str dropped, stripped
    assert result["organizations"] == [{"name": "FEMA", "type": "agency"}]
    assert result["legal_references"] == ["AR 525-13"]
    assert result["courses"] == ["IS-100"]


def test_extract_entities_returns_empty_on_llm_failure() -> None:
    with patch("pipeline.extract.generate_response", side_effect=RuntimeError("down")):
        result = extract_entities("text")

    assert result == {
        "concepts": [],
        "organizations": [],
        "legal_references": [],
        "courses": [],
    }


def test_extract_entities_handles_missing_keys() -> None:
    with patch("pipeline.extract.generate_response", return_value="{}"):
        result = extract_entities("text")

    assert result == {
        "concepts": [],
        "organizations": [],
        "legal_references": [],
        "courses": [],
    }


# --- extract_material_type ----------------------------------------------


def test_extract_material_type_parses_value() -> None:
    raw = '{"material_type": " Training Manual "}'
    with patch("pipeline.extract.generate_response", return_value=raw):
        assert extract_material_type("guide.pdf", "excerpt") == "Training Manual"


def test_extract_material_type_defaults_to_other_when_blank() -> None:
    with patch(
        "pipeline.extract.generate_response", return_value='{"material_type": ""}'
    ):
        assert extract_material_type("f.pdf", "x") == "Other"


def test_extract_material_type_defaults_to_other_on_failure() -> None:
    with patch("pipeline.extract.generate_response", side_effect=RuntimeError()):
        assert extract_material_type("f.pdf", "x") == "Other"
