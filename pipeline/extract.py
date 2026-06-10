"""LLM-based entity extraction for semantic graph enrichment.

Calls the local Ollama model to extract structured entities from chunk text,
and to classify documents into material type categories.
"""

import json
import re
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.llm import generate_response


_ENTITY_PROMPT = """\
Extract named entities from the text below. Return ONLY valid JSON — no explanation, no markdown fences.

Required schema:
{{
  "concepts": ["string"],
  "organizations": [{{"name": "string", "type": "string"}}],
  "legal_references": ["string"],
  "courses": ["string"]
}}

Definitions:
- concepts: key topics, doctrines, technical terms, or domain-specific ideas (not generic words like "information" or "process")
- organizations: named agencies, military units, companies, or governing bodies
- legal_references: specific laws, regulations, directives, or orders (e.g. "AR 525-13", "DoD Directive 2000.12", "10 USC 12304")
- courses: named training programs or educational courses
- Use empty arrays when nothing applies

Text:
{text}"""


_MATERIAL_TYPE_PROMPT = """\
Classify this document into exactly one material type. Return ONLY valid JSON — no explanation, no markdown fences.

Required schema: {{"material_type": "string"}}

Valid values (pick the closest match):
Training Manual, Policy Document, Standard Operating Procedure, Reference Guide,
Course Curriculum, Legal Document, Report, Briefing, Handbook, Other

Filename: {filename}

Document excerpt:
{excerpt}"""


def _parse_json(raw: str) -> dict:
    """Extract the first JSON object from an LLM response."""
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def extract_entities(text: str) -> dict:
    """Extract concepts, organizations, legal references, and courses from chunk text.

    Returns a dict with keys: concepts (list[str]), organizations (list[dict]),
    legal_references (list[str]), courses (list[str]).
    All values are empty lists on failure.
    """
    empty: dict = {"concepts": [], "organizations": [], "legal_references": [], "courses": []}

    prompt = _ENTITY_PROMPT.format(text=text[:3000])
    try:
        raw = generate_response(prompt)
        data = _parse_json(raw)
    except Exception:
        return empty

    return {
        "concepts": [
            c.strip() for c in data.get("concepts", [])
            if isinstance(c, str) and c.strip()
        ],
        "organizations": [
            {"name": o["name"].strip(), "type": o.get("type", "").strip()}
            for o in data.get("organizations", [])
            if isinstance(o, dict) and isinstance(o.get("name"), str) and o["name"].strip()
        ],
        "legal_references": [
            r.strip() for r in data.get("legal_references", [])
            if isinstance(r, str) and r.strip()
        ],
        "courses": [
            c.strip() for c in data.get("courses", [])
            if isinstance(c, str) and c.strip()
        ],
    }


def extract_material_type(filename: str, excerpt: str) -> str:
    """Classify a document into a material type category.

    Returns a material type string. Defaults to "Other" on failure.
    """
    prompt = _MATERIAL_TYPE_PROMPT.format(filename=filename, excerpt=excerpt[:2000])
    try:
        raw = generate_response(prompt)
        data = _parse_json(raw)
        mt = data.get("material_type", "Other")
        return mt.strip() if isinstance(mt, str) and mt.strip() else "Other"
    except Exception:
        return "Other"
