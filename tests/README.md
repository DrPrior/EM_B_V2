# Test Suite Documentation

## Overview

This test suite provides comprehensive validation of the EM_B_V1 Knowledge Graph Chatbot. The tests are organized by module and follow pytest best practices with proper mocking of external dependencies (Neo4j, Ollama API).

## Test Structure

```
tests/
├── __init__.py                 # Test package marker
├── conftest.py                 # Shared fixtures and pytest configuration
├── test_main.py                # FastAPI app initialization and lifespan tests
├── test_chat.py                # Chat router and Pydantic model tests
├── test_embeddings.py          # Embedding generation service tests
├── test_llm.py                 # LLM response generation tests
└── test_rag.py                 # RAG service and vector search tests
```

## Running Tests

### Prerequisites

Ensure you have the required testing dependencies installed:

```bash
pip install pytest pytest-cov pytest-asyncio pytest-mock
```

Or install from requirements:

```bash
pip install -r requirements.txt
```

### Run All Tests

```bash
pytest tests/
```

### Run Tests with Coverage Report

```bash
pytest tests/ --cov=src --cov-report=html --cov-report=term-missing
```

This generates an HTML coverage report in `htmlcov/index.html` and displays coverage summary in terminal.

### Run Specific Test File

```bash
pytest tests/test_chat.py
```

### Run Tests with Verbose Output

```bash
pytest tests/ -v
```

### Run Specific Test Class

```bash
pytest tests/test_embeddings.py::TestGenerateEmbedding
```

### Run Specific Test Function

```bash
pytest tests/test_chat.py::TestChatEndpoint::test_chat_endpoint_success
```

### Run Tests in Watch Mode

```bash
pytest-watch tests/
```

(Requires `pytest-watch` package)

## Test Modules

### test_main.py
Tests FastAPI application initialization, lifespan management, and health check endpoint.

**Key Test Cases:**
- Application metadata (title, version, description)
- Lifespan startup and shutdown
- Neo4j connection initialization
- Health check endpoint response
- Error handling for connection failures

### test_chat.py
Tests chat router endpoints and Pydantic request/response models.

**Key Test Cases:**
- ChatRequest model validation
- ChatResponse model validation
- Chat endpoint with valid questions
- Invalid request handling
- Response model structure verification
- Dependency injection with mocked sessions

### test_embeddings.py
Tests embedding generation through Ollama API.

**Key Test Cases:**
- Successful embedding generation
- Empty response handling
- API error handling
- Correct URL usage
- Large vector dimension handling
- Request payload structure

### test_llm.py
Tests LLM response generation through Ollama API.

**Key Test Cases:**
- Successful response generation
- Empty response handling
- API error handling
- Correct model configuration
- Request payload validation
- Temperature setting validation
- Long prompt handling
- Special character support

### test_rag.py
Tests Retrieval-Augmented Generation service for question answering.

**Key Test Cases:**
- Successful question answering
- Embedding generation error handling
- No relevant results handling
- Response generation error handling
- Multiple document context handling
- Cypher query structure validation
- Prompt format verification

## Mock Strategy

All external dependencies are mocked to ensure isolated unit testing:

### Neo4j Session
- Mocked using `unittest.mock.MagicMock`
- `session.run()` configured to return mock records
- Used in RAG and chat endpoint tests

### Ollama API
- HTTP requests to Ollama mocked with `requests.post`
- Embedding model and LLM model calls isolated
- Configuration values mocked via `settings`

### FastAPI Dependencies
- Neo4jConnection mocked to provide test sessions
- RAGService methods mocked where appropriate
- Dependency injection tested with mock sessions

## Pytest Fixtures

### Shared Fixtures (conftest.py)

- **mock_neo4j_session**: Provides a mocked Neo4j session
- **mock_neo4j_connection**: Provides a mocked Neo4j connection
- **sample_embedding_vector**: 768-dimensional test embedding
- **sample_question**: Sample emergency management question
- **sample_context_documents**: Mock documents from knowledge graph
- **sample_response**: Sample LLM response

### Module-Specific Fixtures

Each test module defines additional fixtures as needed for that module's tests.

## Code Style & Standards

All tests follow the project's Python coding preferences from AGENTS.md:

- **Type Hints**: Full type hints on all functions and methods
- **Docstrings**: Google-style docstrings for all test classes and methods
- **String Formatting**: Exclusively f-strings
- **Assertions**: Using pytest assertions (assert statements)
- **Mocking**: Using `unittest.mock` for dependency injection

## Coverage Goals

Target coverage metrics:

- **Overall**: >90%
- **Critical Paths**: 100% (chat endpoint, RAG service)
- **Services**: >95% (embeddings, LLM, RAG)
- **Routes**: >90% (chat, graph routers)

Current coverage can be checked with:

```bash
pytest tests/ --cov=src --cov-report=term-missing
```

## Common Issues & Solutions

### ModuleNotFoundError: No module named 'src'

Ensure you're running pytest from the project root:

```bash
cd /path/to/EM_B_V1
pytest tests/
```

### Tests fail with "Neo4j connection error"

This is expected with mocked tests. The mocks prevent actual database connections. Ensure all Neo4j interactions are mocked in test setup.

### Ollama API tests failing

Verify that Ollama service is not actually being called. Check that `requests.post` is properly patched with `@patch("src.services.*.requests.post")`.

## Continuous Integration

These tests are designed to run in CI/CD pipelines. Add to your CI configuration:

```yaml
- name: Run tests
  run: pytest tests/ --cov=src --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage.xml
```

## Extending Tests

When adding new features:

1. Create tests first (TDD approach)
2. Use existing fixtures and mock patterns
3. Add new fixtures to conftest.py if reusable
4. Keep tests focused and specific to one behavior
5. Use parametrized tests for multiple similar scenarios:

```python
@pytest.mark.parametrize("input,expected", [
    ("input1", "output1"),
    ("input2", "output2"),
])
def test_multiple_cases(input, expected):
    assert function(input) == expected
```

## Debugging Tests

### Run with pdb on failure

```bash
pytest tests/ --pdb
```

### Run with detailed output

```bash
pytest tests/ -vv --tb=long
```

### Show print statements

```bash
pytest tests/ -s
```

### Run single test for debugging

```bash
pytest tests/test_chat.py::TestChatEndpoint::test_chat_endpoint_success -vv -s
```

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [unittest.mock Documentation](https://docs.python.org/3/library/unittest.mock.html)
- [FastAPI Testing](https://fastapi.tiangolo.com/advanced/testing-dependencies/)
- [Pydantic V2 Testing](https://docs.pydantic.dev/latest/concepts/models/)
