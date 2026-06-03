# Core Module Rules

## Purpose
Contains the primary business logic and operational pipeline for Yosoi: network ingestion, HTML cleaning, AI discovery, verification, extraction, configuration, and task queue management.

## Constraints
1. **Statelessness**: Core components (Fetcher, Cleaner, Discovery, Verifier, Extractor) must be stateless. Pass state via method arguments.
2. **Data Contracts**: Never pass raw unstructured dicts between core components if a model exists. Use `yosoi.models` for I/O boundaries.
3. **Dependency Injection**: Never instantiate `rich.console.Console` deeply inside logic. Require it as an optional constructor argument.
4. **Network Boundaries**: HTTP clients and VoidCrawl browser automation are strictly confined to the `fetcher/` subdirectory. Do not introduce Playwright.
5. **LLM Boundaries**: `pydantic_ai` and LLM interactions are strictly confined to the `discovery/` subdirectory.
6. **Configuration**: `configs.py` holds `YosoiConfig`, `DebugConfig`, `TelemetryConfig`, and provider resolution logic.
7. **Task Queue**: `tasks.py` holds taskiq broker setup, `process_url_task`, `enqueue_urls`, and concurrency helpers.
8. **Pipeline Structure**: `Pipeline` lives in the `pipeline/` package, composed from focused mixin modules — `pipeline/base.py` (spine), `pipeline/cache.py` (cached replay), `pipeline/extraction.py` (fetch/clean/extract), `pipeline/discovery.py` (AI discovery/MCP/JS), `pipeline/crawler.py` (CAS-52 crawl helpers), `pipeline/utils.py` (stateless helpers). `_build_concurrent_table` is defined directly in `pipeline/base.py`. The package `__init__.py` re-exports the public API lazily (PEP 562); `from yosoi.core.pipeline import Pipeline` stays stable.
