from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL for Ollama API",
    )
    chat_model: str = Field(
        default="chat-model",
        description=(
            "Chat model name for Ollama — the custom variant built from Modelfile "
            "by ollama-startup.sh (FROM gemma4:12b-it-qat)"
        ),
    )
    embedding_model: str = Field(
        default="embedding-model",
        description=(
            "Embedding model name for Ollama — the custom variant built from "
            "Modelfile.embeddings by ollama-startup.sh (FROM qwen3-embedding:4b)"
        ),
    )
    max_history_turns: int = Field(
        default=10,
        description="Maximum number of conversation turns to retain per session",
    )
    retrieval_top_k: int = Field(
        default=5,
        description="Number of chunks to retrieve via vector search per query",
    )
    chunk_max_tokens: int = Field(
        default=512,
        description="Maximum token size per ingestion chunk (1 token ≈ 4 chars)",
    )
    chunk_overlap_tokens: int = Field(
        default=64,
        description="Token overlap between consecutive chunks during ingestion",
    )
    vector_retrieval_min_score: float = Field(
        default=0.75,
        description=(
            "Minimum cosine similarity for vector chunks to be included in context"
        ),
    )
    graph_retrieval_min_score: float = Field(
        default=0.78,
        description=(
            "Minimum cosine similarity for graph-augmented chunks to be included "
            "in context"
        ),
    )
    graph_retrieval_limit: int = Field(
        default=3,
        description="Maximum number of graph-augmented chunks to add per query",
    )
    rate_limit_per_minute: int = Field(
        default=20,
        description=(
            "Maximum chat requests allowed per client IP per minute before the "
            "API returns HTTP 429 (protects the API and LLM budget)"
        ),
    )
    data_root: str = Field(
        default="/app/project_data",
        description=(
            "Root directory the ingested source files live under. Used both as "
            "the ingestion root and to resolve cited-source download links served "
            "by the /files endpoint."
        ),
    )


settings = Settings()
