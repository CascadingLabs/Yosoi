# AGENTS.md

## Yosoi Testing Strategy

This project uses a **Tiered Testing Architecture** to balance speed, cost, and reliability.

> [!IMPORTANT]
> **The Pytest Standard**: We strictly use `pytest`. Do not use `unittest.TestCase` classes.
> * Use **fixtures** for setup.
> * Use the `mocker` fixture (from `pytest-mock`) for dependency injection.
> * Use `syrupy` for snapshot assertions.
> * Use `dirty-equals` for loose constraint matching (e.g., timestamps, IDs).
>
>

---

## Testing Tiers

| Level | Type | Directory | Goal | LLM Status | Cost |
| --- | --- | --- | --- | --- | --- |
| **1** | **Unit & Logic** | `tests/unit` | Verify schema validation and prompt construction. | **Deterministic** (`TestModel`) | Free |
| **2** | **Simulated Integration** | `tests/integration` | Verify internal service coordination and I/O logic without real web traffic. | **Mocked** (`respx`, `mocker`) | Free |
| **3** | **Quality Evals** | `tests/evals` | Verify the intelligence and accuracy of the AI on real-world data (not live web). | **Real** (Groq/Gemini) | $$$ |

---

> [!TIP]
> **Assertions Strategy**
> * **Regression (Strict)**: Use **Syrupy** (`assert result == snapshot`) when the output should be identical byte-for-byte every time.
> * **Logic (Flexible)**: Use **Dirty Equals** (`assert result == IsPartialDict(...)`) when you care about the shape of the data but the specific values change.
>
>

---

## Level 1: Deterministic Logic (Pydantic AI)

**Location:** `tests/unit`
**Tools:** `TestModel`, `capture_run_messages`, `dirty-equals`, `polyfactory`

These tests verify that the code surrounding the AI is working. We use `pydantic_ai.models.test.TestModel` to simulate a perfect AI instant response.

### What to Test Here:

* **Schema Validation:** Does the `ScrapingConfig` model reject invalid JSON?
* **Prompt Engineering:** Is the HTML context correctly injected into the system prompt?
* **Retry Logic:** Does the agent handle `ValidationError` correctly?

### Example: Verifying Prompt Construction

```python
import pytest
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel
from yosoi.models import ScrapingConfig

async def test_agent_receives_correct_context(mock_selectors):
    model = TestModel(custom_output_args=mock_selectors)
    agent = Agent(model, output_type=ScrapingConfig)

    html_input = "Secret Data"

    with capture_run_messages() as messages:
        await agent.run(f"Analyze this: {html_input}")

    user_msg = messages[0]
    full_content = " ".join(part.content for part in user_msg.parts if hasattr(part, 'content'))
    assert "Secret Data" in full_content

```

---

## Level 2: Simulated Integration (The Plumbing Layer)

**Location:** `tests/integration`
**Tools:** `pytest-mock`, `respx`, `dirty-equals`, `tmp_path`

These tests verify that Yosoi components talk to each other correctly. **No real web traffic is generated.** We use `respx` to intercept network calls and `tmp_path` to simulate the filesystem.

### What to Test Here:

* **Internal Routing:** Does the Fetcher hand data to the Discovery engine correctly?
* **Mocked Networking:** Does the code handle simulated 404s or 500s from the "web"?
* **Storage Logic:** Does the pipeline write to the correct local directory?

### Example: Intercepting Network Calls with RESPX

```python
import respx
from httpx import Response
from yosoi.pipeline import SelectorDiscoveryPipeline

@respx.mock
def test_pipeline_handles_mocked_404():
    # Intercept the call before it leaves your machine
    respx.get("https://example.com").mock(return_value=Response(404))

    pipeline = SelectorDiscoveryPipeline()
    success = pipeline.process_url("https://example.com")

    assert success is False

```

---

## Level 3: Quality Evals (DeepEval & Real AI)

**Location:** `tests/evals`
**Tools:** `deepeval`, `syrupy`, `pytest-xdist`

These tests are slow and cost money. They verify if the AI is actually smart enough to find selectors on real-world snapshots.

### 1. Snapshot Testing (Syrupy)

Ensures the AI's output remains stable for a given piece of HTML.

```python
def test_snapshot_stability(snapshot, url, html):
    result = discovery.discover(url, html)
    assert result == snapshot

```

### 2. Semantic Evaluation (DeepEval)

Uses LLM-as-a-judge to grade the quality of discovered selectors.

```python
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

def test_selector_quality(url, html):
    result = discovery.discover(url, html)

    quality_metric = GEval(
        name="Selector Specificity",
        criteria="Is the selector specific enough to avoid noise?",
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.8
    )

    assert_test(LLMTestCase(input=html, actual_output=str(result)), [quality_metric])

```

---

## Tooling Reference

* **`pytest-mock`**: Use the `mocker` fixture.
* **`respx`**: Use `@respx.mock` to simulate HTTP traffic.
* **`syrupy`**: For snapshot testing via the `snapshot` fixture.
* **`dirty-equals`**: For flexible pattern matching.
* **`polyfactory`**: For auto-generating Pydantic model test data.
* **`pytest-xdist`**: Run evals in parallel: `pytest -n 4`.


---

## Directory-Based Test Marking

Tests are automatically marked based on their directory location in `tests/conftest.py`:

- `tests/unit/` → `@pytest.mark.unit`
- `tests/integration/` → `@pytest.mark.integration`
- `tests/evals/` → `@pytest.mark.evals`

## How to run

We use poe tasks from pyproject.toml for running tests. Ensure you are in the correct directory (Yosoi root) to run tests correctly.

```
uv run poe evals
uv run poe integration
uv run poe unit
```

---
