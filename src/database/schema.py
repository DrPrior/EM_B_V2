from typing import LiteralString
from neo4j import Driver # type: ignore[import-untyped]

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

# Ensure documents are uniquely identified (using file_name for this example, 
# though a full file_path or UUID is often better in practice)
CONSTRAINT_DOCUMENT = """
CREATE CONSTRAINT unique_document_filename IF NOT EXISTS 
FOR (d:Document) REQUIRE d.file_name IS UNIQUE;
"""

#Add an index on the sequence_number so ordering chunks is fast
INDEX_CHUNK_SEQUENCE = """
CREATE INDEX chunk_sequence_idx IF NOT EXISTS 
FOR (c:Chunk) ON (c.sequence_number);
"""


# --- SEMANTIC NODE CONSTRAINTS ---

# Ensure domain-specific entities are not duplicated
CONSTRAINT_ORGANIZATION = """
CREATE CONSTRAINT unique_organization_name IF NOT EXISTS FOR (o:Organization) REQUIRE o.name IS UNIQUE;
"""
CONSTRAINT_CONCEPT = """
CREATE CONSTRAINT unique_concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE;
"""
CONSTRAINT_LEGAL_REFERENCE = """
CREATE CONSTRAINT unique_legal_ref_name IF NOT EXISTS FOR (l:LegalReference) REQUIRE l.name IS UNIQUE;
"""
CONSTRAINT_COURSE = """
CREATE CONSTRAINT unique_course_name IF NOT EXISTS FOR (c:Course) REQUIRE c.name IS UNIQUE;
"""
CONSTRAINT_MATERIAL_TYPE = """
CREATE CONSTRAINT unique_material_name IF NOT EXISTS FOR (m:MaterialType) REQUIRE m.name IS UNIQUE;
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

MERGE_DOCUMENT = """
MATCH (d:Directory {path: $dir_path})
MERGE (doc:Document {filepath: $filepath})
ON CREATE SET doc.filename = $filename, doc.extension = $extension
MERGE (d)-[:CONTAINS_FILE]->(doc)
"""

MERGE_CHUNK = """
MATCH (doc:Document {filepath: $filepath})
MERGE (c:Chunk {chunk_id: $chunk_id})
ON CREATE SET c.text = $text, c.sequence = $sequence
MERGE (doc)-[:HAS_CHUNK]->(c)
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
MATCH (doc:Document {filepath: $filepath})
MATCH (course:Course {name: $name})
MERGE (doc)-[:REFERENCES]->(course)
"""

LINK_DOC_MATERIAL_TYPE = """
MATCH (doc:Document {filepath: $filepath})
MATCH (mt:MaterialType {name: $name})
MERGE (doc)-[:IS_TYPE]->(mt)
"""

MARK_CHUNK_ENRICHED = """
MATCH (c:Chunk {chunk_id: $chunk_id})
SET c.enriched = true
"""

# ==========================================
# 6. ENRICHMENT FETCH QUERIES
# ==========================================

FETCH_UNENRICHED_CHUNKS = """
MATCH (doc:Document)-[:HAS_CHUNK]->(c:Chunk)
WHERE c.enriched IS NULL
RETURN c.chunk_id AS chunk_id, c.text AS text,
       doc.filepath AS filepath, doc.filename AS filename
ORDER BY doc.filepath, c.sequence
"""

FETCH_DOCS_WITHOUT_MATERIAL_TYPE = """
MATCH (doc:Document)
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
        CONSTRAINT_DOCUMENT,
        INDEX_CHUNK_SEQUENCE,
        CONSTRAINT_ORGANIZATION,
        CONSTRAINT_CONCEPT,
        CONSTRAINT_LEGAL_REFERENCE,
        CONSTRAINT_COURSE,
        CONSTRAINT_MATERIAL_TYPE,
        INDEX_VECTOR_CHUNK,
    ]

    with driver.session() as session:
        session.run("DROP INDEX chunk_vector_idx IF EXISTS")
        for query in queries:
            session.run(query)