FROM astral/uv:python3.12-bookworm-slim

WORKDIR /app

# Install system tools
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN uv venv && \
    uv pip install -r requirements.txt

# Copy application code
COPY src ./src
COPY pipeline ./pipeline
COPY project_data ./project_data

# Start FastAPI application with uvicorn
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
