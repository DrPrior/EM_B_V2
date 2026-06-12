#!/bin/sh
ollama serve &
SERVE_PID=$!

# Wait for ollama to be ready
until ollama list > /dev/null 2>&1; do
  sleep 2
done

# Pull models
ollama pull gemma4:12b-it-qat
ollama pull qwen3-embedding:4b
ollama create chat-model -f /Modelfile
ollama create embedding-model -f /Modelfile.embeddings

# Keep the serve process alive
wait $SERVE_PID
