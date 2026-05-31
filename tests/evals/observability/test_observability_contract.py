"""Run the observability span-contract eval set and fail on any contract miss.

Deterministic — no live LLM, network, or browser (see :mod:`.contract`). Runs
the :mod:`pydantic_evals` dataset serially (``max_concurrency=1``) so the
isolated per-scenario span capture never races on the patched ``obs`` singleton.
"""

from __future__ import annotations

from typing import Any

import pytest

from yosoi.utils import observability as obs

from .contract import build_dataset, run_scenario

_EXPECTED_CASES = {'llm-api', 'llm-claude-sdk', 'llm-opencode', 'a3-disabled', 'a3-probe', 'a3-replay', 'a3-fell-back'}


@pytest.fixture(autouse=True)
def _clean_obs():
    obs.reset_for_tests()
    yield
    obs.reset_for_tests()


async def test_observability_span_contract() -> None:
    report = await build_dataset().evaluate(run_scenario, max_concurrency=1, progress=False)

    # Guard against vacuous passes: every scenario must have run and produced
    # assertions (a task that raised would surface as an empty/absent case).
    assert {c.name for c in report.cases} == _EXPECTED_CASES, 'scenario set drifted from the expected views'

    failures: dict[str, Any] = {}
    for case in report.cases:
        if case.evaluator_failures:
            failures[case.name] = [str(f) for f in case.evaluator_failures]
            continue
        assert case.assertions, f'{case.name}: task produced no assertions (driver likely raised)'
        missed = {name: res.value for name, res in case.assertions.items() if not res.value}
        if missed:
            failures[case.name] = missed

    assert not failures, f'observability span contract violated: {failures}'
