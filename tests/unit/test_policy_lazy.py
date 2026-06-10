"""Lazy-loading guards for the ``yosoi.policy`` package (PEP 562 — see AGENTS.md).

Importing ``yosoi`` or ``yosoi.policy`` must not eagerly pull the policy run/core
submodules or the heavy pydantic-ai / parsel graph. Resolution-time imports
(``yosoi.core.configs``, ``yosoi.core.discovery``) stay lazy so the per-call edge
and short-lived subprocesses keep a low import cost.
"""

from __future__ import annotations

import subprocess
import sys


def _import_probe(body: str) -> str:
    """Run ``body`` in a fresh interpreter so sys.modules starts clean."""
    result = subprocess.run([sys.executable, '-c', body], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def test_import_yosoi_does_not_eagerly_load_policy_submodules() -> None:
    out = _import_probe(
        'import sys, yosoi; '
        "print(','.join(m for m in ('yosoi.policy.run', 'yosoi.policy.core', 'pydantic_ai', 'parsel') "
        'if m in sys.modules))'
    )
    assert out == '', f'eagerly loaded: {out}'


def test_touching_policy_names_stays_light() -> None:
    out = _import_probe(
        'import sys, yosoi.policy; '
        '_ = yosoi.policy.Policy, yosoi.policy.ScrapePolicy, yosoi.policy.ModelPolicy; '
        "print(','.join(m for m in ('pydantic_ai', 'parsel', 'yosoi.core.discovery') if m in sys.modules))"
    )
    assert out == '', f'eagerly loaded: {out}'


def test_policy_public_names_resolve_through_lazy_getattr() -> None:
    import yosoi as ys

    # Names declared in the lazy map must materialize on attribute access.
    assert ys.Policy is not None
    assert ys.ScrapePolicy(cross_origin_dom=True).cross_origin_dom is True
    assert ys.ModelPolicy is not None
