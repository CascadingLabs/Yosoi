# Yosoi Repository Agent Guide

## Context & Philosophy
Yosoi is an AI-powered tool that discovers resilient selectors for web scraping. The core philosophy is "Discover once, scrape forever." We use LLMs to analyze HTML structure and find selectors that are robust to layout changes, then validate them to ensure accuracy.

## Technology Stack & Standards
- **Language**: Python 3.13+
- **Package Manager**: `uv` (Strict requirement. DO NOT use pip/poetry directly).
- **Linting/Formatting**: `ruff`
- **Testing**: `pytest`
- **Type Checking**: `mypy`

## Critical Rules
1. **Dependency Management**: ALWAYS use `uv add` or `uv sync`. never install with pip.
2. **Running Code**: ALWAYS use `uv run <command>`.
   - Example: `uv run yosoi --url ...`
   - Example: `uv run pytest`
3. **Code Style**: Run `uv run ruff check .` and `uv run ruff format .` before finishing a task.
4. **Type Safety**: Maintain strong typing. Use `mypy` to verify.

## Repository Structure
- `yosoi/`: The core python package.
- `tests/`: Integration and unit tests.
- `examples/`: Usage examples.
- `.yosoi/`: Local storage for selectors (gitignored).

## Interaction Guidelines
When working on this repo, generic python solutions often fail. Always check `pyproject.toml` for available scripts and configuration.
