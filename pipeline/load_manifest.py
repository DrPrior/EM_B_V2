"""Manifest loader for the Neo4j knowledge graph.

Parses the markdown manifest tables in ``project_data`` (MANIFEST*.md) and
populates document metadata: each row sets a File node's ``title`` and links it
to Category, Source, Edition, WhyItMatters, and Validated nodes.

Hybrid file resolution: a row is matched to existing File nodes by filename; if
none exist, a catalog File node is created keyed on a synthetic path
``{data_root}/{category}/{filename}`` so that a later ingestion of the real file
(which merges on filepath) attaches its chunks to the same node.

Safe to re-run: every write is a MERGE, and title/metadata links are idempotent.

Run directly:
    # docker exec -it em_b_v1-api-1 python -m pipeline.load_manifest
"""

import re
import sys
from pathlib import Path

from neo4j import ManagedTransaction, Session  # type: ignore[import-untyped]

from src.database import schema
from src.database.connection import Neo4jConnection

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Container path that the ingestion pipeline uses as its root. Synthetic catalog
# filepaths are built under this so they line up with real ingested files.
DEFAULT_DATA_ROOT = "/app/project_data"

# Manifest table columns we care about, keyed by their (normalised) header text.
_REQUIRED_HEADERS = {"filename", "title", "category"}

# Curated cross-document relationships drawn from the manifest prose (the
# "Superseded documents" and "Duplicates" notes), matched by filename. These
# can't be read from the table columns, so they're maintained here by hand.
#
# Superseded files stay fully retrievable — the edge only lets the chatbot flag
# a source as historical and point to the current version.
SUPERSEDES_EDGES: list[tuple[str, str]] = [
    # (newer filename, older filename it supersedes)
    ("CPG-101_EOP_Guide_2025.pdf", "CPG_101_V2_30NOV2010_FINAL_508.pdf"),
    (
        "fema_local-mitigation-planning-policy-guide_042022.pdf",
        "fema-local-mitigation-planning-handbook_03-2013.pdf",
    ),
]

# Each variant points to the canonical (most current / best-validated) copy.
VARIANT_GROUPS: list[dict[str, list[str] | str]] = [
    {
        # CCDS trio — "Deduplicate before training"; 8.22 is the most current.
        "canonical": "FEMA Core Capability Development Sheets (updated 8.22).pdf",
        "variants": [
            "fema_core-capability-development-sheets.pdf",
            "fema_ccds-all-sheets.pdf",
        ],
    },
    {
        # CPG-201 3rd Ed. appears in both tranches under different filenames;
        # the Round 2 copy is content-validated ("yes") vs Tranche 1 ("size").
        "canonical": "CPG-201_THIRA_SPR_3rd.pdf",
        "variants": ["CPG201Final20180525.pdf"],
    },
]


# ==========================================
# MARKDOWN TABLE PARSING
# ==========================================


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into stripped cell values."""
    # Drop the leading/trailing pipe before splitting so we don't get empty ends.
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    """Return True if every cell is a markdown header separator (e.g. ---)."""
    return all(re.fullmatch(r":?-+:?", cell or "") for cell in cells)


def _clean(value: str) -> str:
    """Strip markdown bold markers and surrounding whitespace from a cell."""
    return value.replace("**", "").strip()


def _extract_tranche(content: str, fallback: str) -> str:
    """Derive a tranche label from a manifest's first H1 heading.

    ``# EM Reference Corpus — Round 2 Manifest`` -> ``Round 2``. Falls back to
    the given value (e.g. the file stem) when no recognisable heading is found.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            match = re.search(r"—\s*(.+?)\s+Manifest", heading)
            return match.group(1).strip() if match else heading
    return fallback


def parse_manifest(content: str) -> list[dict[str, str]]:
    """Parse the document table from a manifest markdown file.

    Locates the table whose header contains the document columns (filename,
    title, category, ...) and ignores any other tables or prose in the file.

    Args:
        content: Full text of a manifest markdown file.

    Returns:
        List of row dicts keyed by normalised column header.
    """
    lines = content.splitlines()
    header: list[str] | None = None
    rows: list[dict[str, str]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            # A non-table line ends the table we were reading.
            if header is not None:
                break
            continue

        cells = _split_row(stripped)
        normalised = [c.lower() for c in cells]

        if header is None:
            # Only latch onto the table that has the document columns.
            if _REQUIRED_HEADERS.issubset(set(normalised)):
                header = normalised
            continue

        if _is_separator(cells):
            continue

        if len(cells) != len(header):
            continue  # malformed row — skip defensively

        rows.append({header[i]: cells[i] for i in range(len(header))})

    return rows


# ==========================================
# NEO4J TRANSACTION FUNCTIONS
# ==========================================


def _load_metadata_tx(
    tx: ManagedTransaction, filepath: str, row: dict[str, str], tranche: str
) -> None:
    """Set a File's title and link its manifest metadata nodes, by filepath."""
    filename = row["filename"]
    extension = Path(filename).suffix
    title = _clean(row.get("title", ""))

    tx.run(
        schema.MERGE_CATALOG_FILE,
        filepath=filepath,
        filename=filename,
        extension=extension,
        title=title,
    )

    category = _clean(row.get("category", ""))
    if category:
        tx.run(schema.MERGE_CATEGORY, name=category)
        tx.run(schema.LINK_FILE_CATEGORY, filepath=filepath, name=category)

    source_url = _clean(row.get("source url", ""))
    if source_url.lower().startswith("http"):
        tx.run(schema.MERGE_SOURCE_URL, url=source_url, name=title)
        tx.run(schema.LINK_SOURCE_URL, filepath=filepath, url=source_url)

    edition = _clean(row.get("edition/date", ""))
    if edition and edition != "—":
        tx.run(schema.MERGE_EDITION_DATE, value=edition, description="")
        tx.run(schema.LINK_EDITION_DATE, filepath=filepath, value=edition)

    why = _clean(row.get("why it matters", ""))
    if why:
        tx.run(schema.MERGE_WHY_IT_MATTERS, name=why, description="")
        tx.run(schema.LINK_DOC_WHY_IT_MATTERS, filepath=filepath, name=why)

    validated = _clean(row.get("validated", ""))
    if validated:
        tx.run(schema.MERGE_VALIDATED, name=validated, description="")
        tx.run(schema.LINK_DOC_VALIDATED, filepath=filepath, name=validated)

    # Access level is inferred from the source-URL cell — login-gated entries
    # (e.g. the FEMA EMI courseware ZIPs) say so explicitly; everything else is
    # treated as publicly retrievable.
    access = "login-gated" if "login-gated" in source_url.lower() else "public"
    tx.run(schema.MERGE_ACCESS, level=access)
    tx.run(schema.LINK_FILE_ACCESS, filepath=filepath, level=access)

    if tranche:
        tx.run(schema.MERGE_TRANCHE, name=tranche)
        tx.run(schema.LINK_FILE_TRANCHE, filepath=filepath, name=tranche)


# ==========================================
# PROGRESS DISPLAY
# ==========================================


def _print_section(title: str) -> None:
    print(f"\n{'=' * 44}")
    print(f"  {title}")
    print("=" * 44)


def _print_done(stats: dict[str, int]) -> None:
    width = 44
    print(f"\n{'=' * width}")
    print("  MANIFEST LOAD COMPLETE")
    print("=" * width)
    print(f"  Rows processed   : {stats['rows']}")
    print(f"  Files matched    : {stats['matched']}")
    print(f"  Catalog created  : {stats['created']}")
    print(f"  Supersedes edges : {stats['supersedes']}")
    print(f"  Variant edges    : {stats['variants']}")
    print(f"  Errors           : {stats['errors']}")
    print("=" * width + "\n")


# ==========================================
# MAIN ORCHESTRATOR
# ==========================================


def _resolve_filepaths(
    session: Session, filename: str, category: str, data_root: str
) -> tuple[list[str], bool]:
    """Resolve the File node filepath(s) for a manifest row (hybrid mode).

    Returns ``(filepaths, created)`` where ``created`` is True when no existing
    File matched and a synthetic catalog path was generated instead.
    """
    matches = session.execute_read(
        lambda tx: list(tx.run(schema.FIND_FILE_BY_FILENAME, filename=filename))
    )
    if matches:
        return [record["filepath"] for record in matches], False

    synthetic = f"{data_root}/{category}/{filename}" if category else f"{data_root}/{filename}"
    return [synthetic], True


def load_manifest_file(
    session: Session, path: Path, stats: dict[str, int], data_root: str
) -> None:
    """Parse and load a single manifest markdown file into the graph."""
    _print_section(f"Loading {path.name}")

    content = path.read_text(encoding="utf-8")
    rows = parse_manifest(content)
    tranche = _extract_tranche(content, path.stem)
    total = len(rows)
    if total == 0:
        print("  No document rows found. Skipping.")
        return

    print(f"  Found {total} document rows\n")

    for index, row in enumerate(rows, start=1):
        filename = row.get("filename", "").strip()
        if not filename:
            continue
        category = _clean(row.get("category", ""))

        try:
            filepaths, created = _resolve_filepaths(
                session, filename, category, data_root
            )
            for filepath in filepaths:
                session.execute_write(_load_metadata_tx, filepath, row, tranche)

            stats["rows"] += 1
            if created:
                stats["created"] += 1
            else:
                stats["matched"] += len(filepaths)

            tag = "created" if created else f"matched x{len(filepaths)}"
            pct = int(index / total * 100)
            bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
            print(f"  [{bar}] {pct:3d}%  ({index}/{total})  {filename}  →  {tag}")
        except Exception as e:
            print(f"  ⚠  [{index}/{total}] Failed for {filename}: {e}")
            stats["errors"] += 1


def link_curated_relations(session: Session, stats: dict[str, int]) -> None:
    """Create the curated SUPERSEDES / VARIANT_OF edges between File nodes.

    Run after all rows are loaded so every referenced filename has a File node.
    Edges to a filename with no matching File are silently no-ops (MATCH fails).
    """
    _print_section("Curated cross-document relationships")

    for newer, older in SUPERSEDES_EDGES:
        session.execute_write(
            lambda tx, n=newer, o=older: tx.run(
                schema.LINK_SUPERSEDES, newer=n, older=o
            )
        )
        stats["supersedes"] += 1
        print(f"  SUPERSEDES  {newer}  →  {older}")

    for group in VARIANT_GROUPS:
        canonical = group["canonical"]
        for variant in group["variants"]:
            session.execute_write(
                lambda tx, v=variant, c=canonical: tx.run(
                    schema.LINK_VARIANT_OF, variant=v, canonical=c
                )
            )
            stats["variants"] += 1
            print(f"  VARIANT_OF  {variant}  →  {canonical}")


def load_manifests(session: Session, data_root: str = DEFAULT_DATA_ROOT) -> dict[str, int]:
    """Load every MANIFEST*.md file under data_root into the graph.

    Returns a statistics dictionary.
    """
    stats = {
        "rows": 0,
        "matched": 0,
        "created": 0,
        "supersedes": 0,
        "variants": 0,
        "errors": 0,
    }

    print(f"Starting manifest load from: {data_root}")

    manifests = sorted(Path(data_root).glob("MANIFEST*.md"))
    if not manifests:
        print(f"  No MANIFEST*.md files found under {data_root}")
        return stats

    for path in manifests:
        load_manifest_file(session, path, stats, data_root)

    link_curated_relations(session, stats)

    _print_done(stats)
    return stats


if __name__ == "__main__":
    nc = Neo4jConnection.get_instance()
    try:
        with nc.session() as session:
            load_manifests(session)
    finally:
        nc.close()
