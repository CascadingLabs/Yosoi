# Yosoi Repository Agent Guide

## Context & Philosophy
Yosoi is an AI-powered tool that discovers resilient selectors for web scraping. The core philosophy is "Discover once, scrape forever." We use LLMs to analyze HTML structure and find selectors that are robust to layout changes, then validate them to ensure accuracy.

**Fail Fast**: We do not use fallback heuristics. If AI discovery fails, we fail the process. This ensures we don't return garbage data from unreliable selectors.

## Technology Stack & Standards
- **Language**: Python 3.10+
- **Package Manager**: `uv` (Strict requirement. DO NOT use pip/poetry directly).
- **Linting/Formatting**: `ruff`
- **Testing**: `pytest`
- **Type Checking**: `mypy`
- **Retry Logic**: `tenacity` (Mandatory for all flaky/network operations)

## Retry Logic & Durability
We use `tenacity` to handle retries.
- **DO NOT** use `time.sleep()` in loops.
- **DO** use granular `Retrying` context managers or decorators.
- **DO** use `wait_exponential` to avoid thundering herds.

### Example
```python
from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception_type

# Preferred pattern: Context Manager
for attempt in Retrying(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=10),
    retry=retry_if_exception_type(NetworkError),
    reraise=True
):
    with attempt:
        make_network_call()
```

## Critical Rules
1. **Dependency Management**: ALWAYS use `uv add` or `uv sync`. never install with pip.
2. **Running Code**: ALWAYS use `uv run <command>`.
   - Example: `uv run yosoi --url ...`
   - Example: `uv run pytest`
3. **Code Style**: Run `uv run ruff check .` and `uv run ruff format .` before finishing a task.
4. **Type Safety**: Maintain strong typing. Use `mypy` to verify.
5. **Retry Logic**: Use `tenacity` for all retry patterns. Never implement custom retry loops with `for` or `while`.

## Lazy Loading
Package `__init__.py` files re-export their public API **lazily** (PEP 562). Eager
`from .submodule import X` re-exports forced the whole dependency graph
(pydantic-ai, the provider/Claude/OpenCode SDKs, parsel, dateparser, …) to import
whenever *anything* in or under a package was imported — even a bare
`import yosoi` or one light leaf module. That dragged `import yosoi` to ~1.6s and
taxed every short-lived subprocess (notably the `yosoi-validator-mcp` server,
spawned cold by all three MCP-discovery backends). Lazy exports cut `import yosoi`
to ~0.04s and the validator's cold start from ~1.6s to ~0.3s.

**Convention** — a re-exporting package `__init__.py` looks like:
```python
from __future__ import annotations
from typing import TYPE_CHECKING
from yosoi._lazy import lazy_exports

if TYPE_CHECKING:                       # static typing only — zero runtime cost
    from yosoi.foo.bar import Thing as Thing

_LAZY = {'Thing': 'yosoi.foo.bar'}      # public name -> dotted submodule
__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
```
The `TYPE_CHECKING` block (or, for `yosoi/__init__.py`, the committed
`yosoi/__init__.pyi` stub) keeps mypy and IDEs seeing the full API. Keep the stub,
the `TYPE_CHECKING` imports, and `_LAZY` in lockstep.

**Rules**
- New re-exporting package `__init__`? Use the lazy pattern. Don't add eager
  `from .submodule import X` re-exports.
- **Never lazy-load a package whose `__init__` has import side effects** —
  `yosoi/types` registers coercions on import and stays eager.
- **Never lazy-export a name equal to a sibling submodule** — importing the
  submodule rebinds the parent attribute and clobbers the lazy binding
  (`yosoi.cli` keeps `main` eager for exactly this reason).
- Leaf modules stay normal — lazy loading is only for package `__init__` files.

## Browser Automation Boundary
- **DO NOT use Playwright** in Yosoi implementation code, tests, examples, or smoke scripts.
- **DO use VoidCrawl** and Yosoi's wrappers around it (`JSFetcher`, `HeadlessFetcher`, `HeadfulFetcher`, `DOMLoader`) for rendered browser behavior.
- If VoidCrawl does not expose a needed browser/CDP capability yet, surface that as a VoidCrawl/Yosoi wrapper gap rather than introducing Playwright as a side path.

## Repository Structure
- `yosoi/`: The core python package.
- `tests/`: Integration and unit tests.
- `examples/`: Usage examples.
- `.yosoi/`: Local storage for selectors, debug HTML, and logs (gitignored).
    - `logs/`: Contains run logs in `run_YYYYMMDD_HHMMSS.log` format.
    - `debug_html/`: Extracted HTML for debugging.

## Logging & Observability
- **Local Logs**: Every run generates a log file in `.yosoi/logs/`. These logs contain detailed debug information and full tracebacks.
- **Langfuse**: OSS, self-hostable LLM observability. Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` (and optional `LANGFUSE_BASE_URL`, default cloud) to enable.
  Run a local stack: `docker compose -f docker-compose.langfuse.yml up -d`, then visit `http://localhost:3000` to create a project and copy the keys.
- **Console**: Keeping it minimal and stylish for human eyes.

## Interaction Guidelines
When working on this repo, generic python solutions often fail. Always check `pyproject.toml` for available scripts and configuration.
