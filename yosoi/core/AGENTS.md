# Core Module Rules

## Purpose
Contains the primary business logic and operational pipeline for Yosoi: network ingestion, HTML cleaning, AI discovery, verification, and extraction.

## Constraints
1. **Statelessness**: Core components (Fetcher, Cleaner, Discovery, Verifier, Extractor) must be stateless. Pass state via method arguments.
2. **Data Contracts**: Never pass raw unstructured dicts between core components if a model exists. Use `yosoi.models` for I/O boundaries.
3. **Dependency Injection**: Never instantiate `rich.console.Console` deeply inside logic. Require it as an optional constructor argument.
4. **Network Boundaries**: `requests` and `playwright` are strictly confined to the `fetcher/` subdirectory.
5. **LLM Boundaries**: `pydantic_ai` and LLM interactions are strictly confined to the `discovery/` subdirectory.
