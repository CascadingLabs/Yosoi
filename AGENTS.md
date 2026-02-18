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

## Repository Structure
- `yosoi/`: The core python package.
- `tests/`: Integration and unit tests.
- `examples/`: Usage examples.
- `.yosoi/`: Local storage for selectors, debug HTML, and logs (gitignored).
    - `logs/`: Contains run logs in `run_YYYYMMDD_HHMMSS.log` format.
    - `debug_html/`: Extracted HTML for debugging.

## Logging & Observability
- **Local Logs**: Every run generates a log file in `.yosoi/logs/`. These logs contain detailed debug information and full tracebacks.
- **Logfire**: Used for cloud-based observability if `LOGFIRE_TOKEN` is set.
- **Console**: Keeping it minimal and stylish for human eyes.

## Interaction Guidelines
When working on this repo, generic python solutions often fail. Always check `pyproject.toml` for available scripts and configuration.
