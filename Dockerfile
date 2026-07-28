FROM astral/uv:python3.12-bookworm-slim

WORKDIR /app

# Install system tools
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (dev deps include the test runner; see
# requirements-dev.txt, which itself pulls in requirements.txt). pyproject.toml
# is copied so pytest/ruff config is available inside the container.
COPY requirements.txt requirements-dev.txt pyproject.toml ./
RUN uv venv && \
    uv pip install -r requirements-dev.txt

# Copy application code
COPY src ./src
COPY pipeline ./pipeline
COPY project_data ./project_data

# Modelfiles used by the startup bootstrap to build the custom Ollama variants
# on the host (src/services/ollama_bootstrap.py). Also bind-mounted in
# docker-compose.yml for hot-edit during development.
COPY Modelfile Modelfile.embeddings ./

# Start FastAPI application with uvicorn
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
