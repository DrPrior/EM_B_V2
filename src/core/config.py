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
        description=(
            "Base URL for Ollama API. In the hybrid deployment Ollama runs "
            "natively on the host, so the container overrides this with "
            "http://host.docker.internal:11434 via OLLAMA_BASE_URL."
        ),
    )
    chat_model: str = Field(
        default="chat-model",
        description=(
            "Chat model name for Ollama — the custom variant built from Modelfile "
            "by the startup bootstrap (FROM gemma4:12b-it-qat)"
        ),
    )
    embedding_model: str = Field(
        default="embedding-model",
        description=(
            "Embedding model name for Ollama — the custom variant built from "
            "Modelfile.embeddings by the startup bootstrap (FROM qwen3-embedding:4b)"
        ),
    )
    chat_base_model: str = Field(
        default="gemma4:12b-it-qat",
        description=(
            "Base model the chat-model variant is built FROM. The startup "
            "bootstrap pulls this onto the host before creating chat-model. Must "
            "match the FROM line in Modelfile."
        ),
    )
    embedding_base_model: str = Field(
        default="qwen3-embedding:4b",
        description=(
            "Base model the embedding-model variant is built FROM. The startup "
            "bootstrap pulls this onto the host before creating embedding-model. "
            "Must match the FROM line in Modelfile.embeddings."
        ),
    )
    ollama_startup_retries: int = Field(
        default=5,
        description=(
            "How many times the startup bootstrap pings host Ollama's /api/version "
            "before giving up and exiting (the host may not have launched Ollama "
            "yet when the container boots)."
        ),
    )
    ollama_startup_delay: float = Field(
        default=3.0,
        description=(
            "Seconds to wait between host-Ollama connection attempts during the "
            "startup bootstrap retry loop."
        ),
    )
    ollama_request_timeout: float = Field(
        default=10.0,
        description=(
            "Timeout (seconds) for lightweight bootstrap calls to host Ollama "
            "(/api/version, /api/tags). The model pull uses a much longer timeout."
        ),
    )
    ollama_pull_timeout: float = Field(
        default=1800.0,
        description=(
            "Timeout (seconds) for the blocking /api/pull and /api/create calls "
            "during bootstrap. Generous to cover the first-run ~10GB base-model "
            "download on a cold host."
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
    entity_extraction_max_tokens: int = Field(
        default=256,
        description=(
            "Token cap (num_predict) for the per-query entity-extraction LLM "
            "call. The output is a small JSON object, so a low cap bounds its "
            "latency without truncating typical results."
        ),
    )
    timing_log_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for per-stage query timing logs. When false, the "
            "timing helpers no-op so production can silence them."
        ),
    )
    timing_log_level: str = Field(
        default="INFO",
        description="Log level for the 'em_b.timing' logger (e.g. DEBUG, INFO).",
    )


settings = Settings()
