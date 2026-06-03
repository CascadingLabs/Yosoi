"""The act dispatch table (`_EXECUTORS`) must stay in sync with `ActKind`.

The replay runtime dispatches each act through a table keyed by ``ActKind``
(CAS-87). This guards the one failure mode that table introduces: a newly added
``ActKind`` silently having no executor — or an out-of-band eval kind (ys.python /
ys.llm) being wrongly registered here instead of as a post-replay transform.

If you add an in-tab browser act, register it in ``_EXECUTORS`` and drop it from
``_DEFERRED_KINDS`` below. If you add an out-of-band eval kind, leave it deferred —
it does not belong in this table (see the table's docstring in runtime.py).
"""

from __future__ import annotations

import pytest

from yosoi.core.replay.runtime import _EXECUTORS, ReplayExecutionError, _execute_once
from yosoi.models.replay import ActKind, ReplayAct

# Act kinds intentionally absent from _EXECUTORS because they run as post-execute_plan
# transforms, not in-tab browser acts. Empty today; populated when an out-of-band eval
# kind (ys.python / ys.llm / ys.wasm) lands in ActKind.
_DEFERRED_KINDS: frozenset[ActKind] = frozenset()


def test_every_act_kind_is_registered_or_explicitly_deferred():
    """No ActKind may silently fall through: it is either dispatchable or deferred."""
    missing = set(ActKind) - set(_EXECUTORS) - _DEFERRED_KINDS
    assert not missing, (
        f'ActKind(s) {sorted(k.value for k in missing)} have no executor and are not in '
        '_DEFERRED_KINDS. Register an in-tab executor, or defer out-of-band evals.'
    )


def test_table_and_deferred_sets_are_disjoint():
    """A kind cannot be both dispatchable and deferred."""
    assert not (set(_EXECUTORS) & _DEFERRED_KINDS)


def test_out_of_band_eval_kinds_are_never_registered_in_table():
    """Out-of-band evals (EVAL_PYTHON / EVAL_WASM / EVAL_LLM) must NOT be in _EXECUTORS.

    This is the real failure mode the table introduces, and the one the docstring policy
    can't enforce: when such a kind is added to ``ActKind``, the path of least resistance
    to a green build is to drop it into ``_EXECUTORS`` — the exact forbidden move, since
    those run as post-``execute_plan`` transforms, not on the deterministic replay hot path.
    ``EVAL`` (in-tab JS) is intentionally NOT matched — only the ``EVAL_<runtime>`` family.
    Tautological today (no such kinds exist yet) and becomes load-bearing the moment one does.
    """
    misfiled = sorted(k for k in _EXECUTORS if k.name.startswith('EVAL_'))
    assert not misfiled, (
        f'out-of-band eval kind(s) {misfiled} are registered in _EXECUTORS; they must run '
        'as post-execute_plan transforms, not in-tab acts. Remove them from the table.'
    )


@pytest.mark.asyncio
async def test_deferred_kinds_fail_loud_not_silent():
    """A deferred kind raises fail-fast rather than returning a silent None.

    Skips cleanly while _DEFERRED_KINDS is empty; becomes a real assertion the moment
    an out-of-band eval kind is added, proving the loud-default still holds for it.
    """
    if not _DEFERRED_KINDS:
        pytest.skip('no deferred kinds yet')
    for kind in _DEFERRED_KINDS:
        act = ReplayAct.model_construct(kind=kind)
        with pytest.raises(ReplayExecutionError, match='unsupported act kind'):
            await _execute_once(object(), act)
