# Yosoi Project Architecture Guide

## Directory Structure
The `yosoi/` package is organized into several sub-packages to maintain a clean separation of concerns.

### `core/` (Network Ingestion & Core Logic)
- **`pipeline.py`**: The orchestrator. Manages the high-level flow from URL to saved selectors.
- **`fetcher/`**: Multi-layered fetcher system.
    - `base.py`: Base classes and content detection.
    - `simple.py`: Standard HTTP requests.
    - `playwright.py`: Browser-based extraction.
    - `smart.py`: Waterfall strategy (simple -> playwright).
- **`discovery/`**: AI-powered selector discovery.
    - `agent.py`: Pydantic AI agent implementation.
    - `config.py`: LLM provider configurations (Groq, Gemini, OpenAI).
- **`cleaning/`**: HTML noise reduction to minimize token usage.
- **`extraction/`**: Logic for pulling content using verified selectors.
- **`verification/`**: Verification system to check selectors against real HTML.

### `models/` (Data Contracts)
- **`selectors.py`**: Pydantic models for selector structures.
- **`results.py`**: Models for fetch results and verification statuses.

### `storage/` (Persistence)
- **`persistence.py`**: Handles JSON storage of selectors and content.
- **`tracking.py`**: Tracks LLM usage and efficiency.
- **`debug.py`**: Manages debug output (HTML/selectors).

### `outputs/` (Presentation)
- **`json.py`**, **`markdown.py`**: Format-specific output logic.
- **`utils.py`**: Formatting dispatcher.

### `utils/` (General Utilities)
- **`files.py`**: Filesystem paths and initialization.
- **`logging.py`**: Local file-based logging setup.
- **`headers.py`**: Realistic header and UA generation.
- **`prompts.py`**: Prompt loader.
- **`exceptions.py`**: Custom exceptions for the Yosoi package.
- **`retry.py`**: Standardized retry logic.

## Development Guidelines
- **Import Strategy**: Prefer absolute imports from the `yosoi` root.
- **Clean API**: Use `yosoi/__init__.py` to export the primary `Pipeline` and `LLMConfig`.
- **Statelessness**: Favor stateless core components that receive state via arguments.
- **Observability**: Instrument all major operations with `logfire`.
- **Output**: Use `rich` for all terminal UI elements.
