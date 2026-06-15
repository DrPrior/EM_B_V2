from typing import LiteralString

from neo4j import Driver  # type: ignore[import-untyped]

# ==========================================
# 1. INITIALIZATION: Constraints & Indexes
# ==========================================
# These queries are run exactly once when the app starts up.
# They tell Neo4j to enforce strict rules on the data structure.

# Ensure every directory path is unique
CONSTRAINT_DIRECTORY = """
CREATE CONSTRAINT unique_directory_path IF NOT EXISTS
FOR (d:Directory) REQUIRE d.path IS UNIQUE;
"""

# Ensure files are uniquely identified by their full path (the key MERGE_FILE
# and the ingestion pipeline merge on — filename alone collides across directories)
CONSTRAINT_FILE = """
CREATE CONSTRAINT unique_file_filepath IF NOT EXISTS
FOR (d:File) REQUIRE d.filepath IS UNIQUE;
"""

# Add an index on the sequence_number so ordering chunks is fast
INDEX_CHUNK_SEQUENCE = """
CREATE INDEX chunk_sequence_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.sequence_number);
"""


# --- SEMANTIC NODE CONSTRAINTS ---

# Ensure domain-specific entities are not duplicated
CONSTRAINT_ORGANIZATION = """
CREATE CONSTRAINT unique_organization_name IF NOT EXISTS
FOR (o:Organization) REQUIRE o.name IS UNIQUE;
"""
CONSTRAINT_CONCEPT = """
CREATE CONSTRAINT unique_concept_name IF NOT EXISTS
FOR (c:Concept) REQUIRE c.name IS UNIQUE;
"""
CONSTRAINT_LEGAL_REFERENCE = """
CREATE CONSTRAINT unique_legal_ref_name IF NOT EXISTS
FOR (l:LegalReference) REQUIRE l.name IS UNIQUE;
"""
CONSTRAINT_COURSE = """
CREATE CONSTRAINT unique_course_name IF NOT EXISTS
FOR (c:Course) REQUIRE c.name IS UNIQUE;
"""
CONSTRAINT_MATERIAL_TYPE = """
CREATE CONSTRAINT unique_material_name IF NOT EXISTS
FOR (m:MaterialType) REQUIRE m.name IS UNIQUE;
"""
CONSTRAINT_WHY_IT_MATTERS = """
CREATE CONSTRAINT unique_why_it_matters_name IF NOT EXISTS
FOR (w:WhyItMatters) REQUIRE w.name IS UNIQUE;
"""
CONSTRAINT_SOURCE_URL = """
CREATE CONSTRAINT unique_source_url IF NOT EXISTS
FOR (s:Source) REQUIRE s.url IS UNIQUE;
"""
CONSTRAINT_EDITION_DATE = """
CREATE CONSTRAINT unique_edition_value IF NOT EXISTS
FOR (e:Edition) REQUIRE e.value IS UNIQUE;
"""
CONSTRAINT_VALIDATED = """
CREATE CONSTRAINT unique_validation_name IF NOT EXISTS
FOR (v:Validated) REQUIRE v.name IS UNIQUE;
"""
CONSTRAINT_CATEGORY = """
CREATE CONSTRAINT unique_category_name IF NOT EXISTS
FOR (cat:Category) REQUIRE cat.name IS UNIQUE;
"""
CONSTRAINT_TRANCHE = """
CREATE CONSTRAINT unique_tranche_name IF NOT EXISTS
FOR (t:Tranche) REQUIRE t.name IS UNIQUE;
"""
CONSTRAINT_ACCESS = """
CREATE CONSTRAINT unique_access_level IF NOT EXISTS
FOR (a:Access) REQUIRE a.level IS UNIQUE;
"""

# Add a vector index for chunk embeddings (dimensions match qwen3-embedding:4b: 2560)
INDEX_VECTOR_CHUNK = """
CREATE VECTOR INDEX chunk_vector_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 2560,
  `vector.similarity_function`: 'cosine'
}}
"""

# ==========================================
# 2. STRUCTURAL INGESTION QUERIES (Phases 2 & 3)
# ==========================================
# Used by your pipeline to build the file system tree.

MERGE_DIRECTORY = """
MERGE (d:Directory {path: $path})
ON CREATE SET d.name = $name
"""

MERGE_FILE = """
MATCH (d:Directory {path: $dir_path})
MERGE (doc:File {filepath: $filepath})
ON CREATE SET doc.filename = $filename, doc.extension = $extension,
              doc.title = $title
MERGE (d)-[:CONTAINS_FILE]->(doc)
"""

MERGE_CHUNK = """
MATCH (doc:File {filepath: $filepath})
MERGE (c:Chunk {chunk_id: $chunk_id})
ON CREATE SET c.text = $text, c.sequence = $sequence
MERGE (doc)-[:HAS_CHUNK]->(c)
"""

# Look up existing File nodes by filename (filename is not unique across
# directories, so this may return several filepaths).
FIND_FILE_BY_FILENAME = """
MATCH (f:File {filename: $filename})
RETURN f.filepath AS filepath
"""

# Merge a File from manifest metadata. Unlike MERGE_FILE this does not require a
# parent Directory, so it can create catalog entries for files not yet ingested.
# When the real file is later ingested, the MERGE matches on filepath and chunks
# are attached to the same node. title is always (re)set — the manifest is the
# authoritative source for it.
MERGE_CATALOG_FILE = """
MERGE (f:File {filepath: $filepath})
ON CREATE SET f.filename = $filename, f.extension = $extension
SET f.title = $title
"""

# ==========================================
# 3. SEMANTIC INGESTION QUERIES (Phase 5)
# ==========================================
# Used by your batch processor using UNWIND to insert LLM JSON.

MERGE_ENTITIES_BATCH = """
UNWIND $entities AS entity
MERGE (e:Entity {name: entity.name})
ON CREATE SET e.type = entity.type
"""

# ==========================================
# 4. SEMANTIC NODE MERGE QUERIES (Phase 5)
# ==========================================

MERGE_CONCEPT = """
MERGE (c:Concept {name: $name})
ON CREATE SET c.description = $description
"""

MERGE_ORGANIZATION = """
MERGE (o:Organization {name: $name})
ON CREATE SET o.type = $type
"""

MERGE_LEGAL_REFERENCE = """
MERGE (l:LegalReference {name: $name})
ON CREATE SET l.citation = $citation
"""

MERGE_COURSE = """
MERGE (c:Course {name: $name})
ON CREATE SET c.code = $code
"""

MERGE_MATERIAL_TYPE = """
MERGE (m:MaterialType {name: $name})
"""

MERGE_WHY_IT_MATTERS = """
MERGE (w:WhyItMatters {name: $name})
ON CREATE SET w.description = $description
"""

MERGE_SOURCE_URL = """
MERGE (s:Source {url: $url})
ON CREATE SET s.name = $name
"""

MERGE_EDITION_DATE = """
MERGE (e:Edition {value: $value})
ON CREATE SET e.description = $description
"""

MERGE_VALIDATED = """
MERGE (v:Validated {name: $name})
ON CREATE SET v.description = $description
"""

MERGE_CATEGORY = """
MERGE (cat:Category {name: $name})
"""

MERGE_TRANCHE = """
MERGE (t:Tranche {name: $name})
"""

MERGE_ACCESS = """
MERGE (a:Access {level: $level})
"""

# ==========================================
# 5. SEMANTIC RELATIONSHIP QUERIES
# ==========================================

LINK_CHUNK_CONCEPT = """
MATCH (chunk:Chunk {chunk_id: $chunk_id})
MATCH (concept:Concept {name: $name})
MERGE (chunk)-[:MENTIONS]->(concept)
"""

LINK_CHUNK_ORGANIZATION = """
MATCH (chunk:Chunk {chunk_id: $chunk_id})
MATCH (org:Organization {name: $name})
MERGE (chunk)-[:MENTIONS]->(org)
"""

LINK_CHUNK_LEGAL_REF = """
MATCH (chunk:Chunk {chunk_id: $chunk_id})
MATCH (ref:LegalReference {name: $name})
MERGE (chunk)-[:CITES]->(ref)
"""

LINK_DOC_COURSE = """
MATCH (doc:File {filepath: $filepath})
MATCH (course:Course {name: $name})
MERGE (doc)-[:REFERENCES]->(course)
"""

LINK_DOC_MATERIAL_TYPE = """
MATCH (doc:File {filepath: $filepath})
MATCH (mt:MaterialType {name: $name})
MERGE (doc)-[:IS_TYPE]->(mt)
"""
LINK_DOC_WHY_IT_MATTERS = """
MATCH (doc:File {filepath: $filepath})
MATCH (wim:WhyItMatters {name: $name})
MERGE (doc)-[:EXPLAINS]->(wim)
"""

LINK_WHY_IT_MATTERS_CONCEPT = """
MATCH (wim:WhyItMatters {name: $name})
MATCH (concept:Concept {name: $concept_name})
MERGE (wim)-[:RELATES_TO]->(concept)
"""
LINK_SOURCE_URL = """
MATCH (doc:File {filepath: $filepath})
MATCH (source:Source {url: $url})
MERGE (doc)-[:HAS_SOURCE]->(source)
"""
LINK_EDITION_DATE = """
MATCH (doc:File {filepath: $filepath})
MATCH (edition:Edition {value: $value})
MERGE (doc)-[:HAS_EDITION]->(edition)
"""
LINK_FILE_CATEGORY = """
MATCH (doc:File {filepath: $filepath})
MATCH (cat:Category {name: $name})
MERGE (doc)-[:IN_CATEGORY]->(cat)
"""
LINK_DOC_VALIDATED = """
MATCH (doc:File {filepath: $filepath})
MATCH (v:Validated {name: $name})
MERGE (doc)-[:HAS_VALIDATION]->(v)
"""
LINK_FILE_TRANCHE = """
MATCH (doc:File {filepath: $filepath})
MATCH (t:Tranche {name: $name})
MERGE (doc)-[:FROM_TRANCHE]->(t)
"""
LINK_FILE_ACCESS = """
MATCH (doc:File {filepath: $filepath})
MATCH (a:Access {level: $level})
MERGE (doc)-[:HAS_ACCESS]->(a)
"""

# --- CURATED CROSS-DOCUMENT RELATIONSHIPS ---
# File-to-file edges sourced from the manifest prose (supersession / duplicate
# notes), matched by filename. Superseded files are NOT removed from retrieval —
# the edge is informational so the chatbot can flag a source as historical.

LINK_SUPERSEDES = """
MATCH (newer:File {filename: $newer})
MATCH (older:File {filename: $older})
MERGE (newer)-[:SUPERSEDES]->(older)
"""

LINK_VARIANT_OF = """
MATCH (variant:File {filename: $variant})
MATCH (canonical:File {filename: $canonical})
MERGE (variant)-[:VARIANT_OF]->(canonical)
"""

MARK_CHUNK_ENRICHED = """
MATCH (c:Chunk {chunk_id: $chunk_id})
SET c.enriched = true
"""

# ==========================================
# 6. ENRICHMENT FETCH QUERIES
# ==========================================

FETCH_UNENRICHED_CHUNKS = """
MATCH (doc:File)-[:HAS_CHUNK]->(c:Chunk)
WHERE c.enriched IS NULL
RETURN c.chunk_id AS chunk_id, c.text AS text,
       doc.filepath AS filepath, doc.filename AS filename
ORDER BY doc.filepath, c.sequence
"""

FETCH_DOCS_WITHOUT_MATERIAL_TYPE = """
MATCH (doc:File)
WHERE NOT (doc)-[:IS_TYPE]->(:MaterialType)
OPTIONAL MATCH (doc)-[:HAS_CHUNK]->(c:Chunk)
WITH doc, c ORDER BY c.sequence
WITH doc, collect(c.text)[0] AS first_chunk_text
RETURN doc.filepath AS filepath, doc.filename AS filename, first_chunk_text
"""


def setup_constraints(driver: Driver) -> None:
    """Executes the constraint queries against the database."""
    queries: list[LiteralString] = [
        CONSTRAINT_DIRECTORY,
        CONSTRAINT_FILE,
        INDEX_CHUNK_SEQUENCE,
        CONSTRAINT_ORGANIZATION,
        CONSTRAINT_CONCEPT,
        CONSTRAINT_LEGAL_REFERENCE,
        CONSTRAINT_COURSE,
        CONSTRAINT_MATERIAL_TYPE,
        CONSTRAINT_WHY_IT_MATTERS,
        CONSTRAINT_SOURCE_URL,
        CONSTRAINT_EDITION_DATE,
        CONSTRAINT_VALIDATED,
        CONSTRAINT_CATEGORY,
        CONSTRAINT_TRANCHE,
        CONSTRAINT_ACCESS,
        INDEX_VECTOR_CHUNK,
    ]

    with driver.session() as session:
        session.run("DROP INDEX chunk_vector_idx IF EXISTS")
        for query in queries:
            session.run(query)
