"""Regression for the Google SERP use case (examples/tutorial/serp_google/google_serp.py).

The example is the spike's runnable dogfood; this pins its end-to-end behavior so a
future engine change that breaks the teleport / parametrized-replay / captcha-reaction
wiring fails CI instead of silently rotting the demo.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_DEMO = Path(__file__).resolve().parents[2] / 'examples' / 'tutorial' / 'serp_google' / 'google_serp.py'
_MODNAME = 'serp_google_demo'


def _load_demo() -> ModuleType:
    # Load ONCE: re-executing the module re-declares its OrganicResult/AdResult
    # contracts, which the name-keyed contract registry rejects as duplicates.
    if _MODNAME in sys.modules:
        return sys.modules[_MODNAME]
    spec = importlib.util.spec_from_file_location(_MODNAME, _DEMO)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODNAME] = module
    spec.loader.exec_module(module)
    return module


def test_demo_module_imports() -> None:
    assert _DEMO.exists()
    _load_demo()


async def test_demo_reacts_to_captcha_and_resumes() -> None:
    """30 searches, a reCAPTCHA on #12: react via the bus, hot-swap, resume — all extract."""
    demo = _load_demo()
    rep = await demo.run_demo(queries=30, captcha_on=12)

    assert rep['rows_per_query'] == [2] * 30  # every query extracted, including post-captcha
    assert rep['captcha_episodes'] == 1
    assert len(rep['learn_calls']) == 1  # bus dedup: one resolution for the description
    assert rep['reaction_state_after'] == 'learned'  # UNLEARNED -> hot-swapped LEARNED
    assert rep['teleport_geo'] == (38.2527, -85.7585)  # teleport applied before first paint
    assert rep['mouse_events']  # humanized click dispatched during recovery


def test_ad_and_organic_contracts_get_distinct_signatures() -> None:
    """W5: same {url,title} shape, different docstring -> distinct cache signatures."""
    from yosoi.utils.signatures import contract_signature

    demo = _load_demo()
    assert contract_signature(demo.OrganicResult) != contract_signature(demo.AdResult)
