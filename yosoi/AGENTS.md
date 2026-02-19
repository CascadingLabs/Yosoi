# Yosoi Package Agent Guide

## Purpose
This directory (`yosoi/`) contains the core application logic. It is structured as a modular pipeline where each module has a single responsibility.

## Core Modules
- **`pipeline.py`**: The orchestrator. It manages the flow of data from URL to saved selectors.
- **`fetcher.py`**: Handles network requests, bot detection avoidance, and HTML retrieval.
- **`cleaner.py`**: Reduces HTML noise (removes scripts, styles) to minimize token usage for the LLM.
- **`discovery.py`**: Interfaces with the LLM (Groq/Gemini) to identify selectors.
- **`validator.py`**: Verifies that discovered selectors actually work on the provided HTML.
- **`extractor.py`**: Uses validated selectors to pull content.
- **`storage.py`**: Manages JSON persistence of selectors.
- **`exceptions.py`**: Custom exceptions for the Yosoi package.
- **`cli.py`**: Entry point for terminal interaction.

## Development Guidelines
- **Modularity**: keep classes focused. `Fetcher` shouldn't know about `LLMConfig`.
- **Observability**: Use `logfire` for tracing important operations.
- **Output**: Use `rich` for all user-facing terminal output.
