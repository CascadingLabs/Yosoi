"""Regression harness for the distilled page-class reuse detector.

The user's explicit ask: "tell when there's a regression in this detection model,
fast, because everything's radically typed."

Three layers, fail-closed bias (a LEAK = wrong data shipped silently = cardinal sin):
  1. per-case: every must-refuse fixture must NOT be allowed (named, parametrized).
  2. aggregate gate: leaks == 0 is the only hard pass/fail; false alarms ratchet.
  3. leave-one-domain-out is covered by distill.py; here we pin the rule detector.

Run:  uv run pytest experiments/scope_spike/test_detector.py -v
A regression surfaces as a NAMED case failing (e.g. test_no_leak[reddit#user/spez]),
pointing straight at the domain + page that broke — not a mystery accuracy drop.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from detector import Obs, Verdict, decide

HERE = Path(__file__).parent
DOMAINS = HERE / 'fixtures' / 'domains'

# Leak budget: the cardinal sin. Zero tolerated. Ratchet false alarms only.
MAX_LEAKS = 0
MAX_FALSE_ALARMS = 6  # >= the card+struct algorithmic baseline (5); tighten over time


def _obs(p: dict) -> Obs:
    return Obs(
        url=p.get('href', ''),
        title=p.get('title', ''),
        rows=int(p.get('rows', 0) or 0),
        body_class=p.get('bodyClass', '') or '',
        tag_hist=dict(p.get('tagHist', [])),
    )


def _load() -> list[tuple[str, Obs, Obs, bool]]:
    """Yield (case_id, seed, replay, should_allow) for every replay decision."""
    cases = []
    for f in sorted(DOMAINS.glob('*.json')):
        d = json.loads(f.read_text())
        pages = [p for p in d.get('pages', []) if not p.get('blocked')]
        seed = next((p for p in pages if p.get('role') == 'seed'), None)
        if not seed:
            continue
        s = _obs(seed)
        for p in pages:
            if p.get('role') == 'seed':
                continue
            cid = f'{d.get("domain", f.stem)}::{p.get("role")}::{p.get("href", "")[-28:]}'
            cases.append((cid, s, _obs(p), p.get('role') == 'must-transfer'))
    return cases


CASES = _load()
REFUSE_CASES = [c for c in CASES if not c[3]]
TRANSFER_CASES = [c for c in CASES if c[3]]


def test_fixtures_present() -> None:
    """Guard the harness itself: fixtures must exist and be balanced-ish."""
    assert len(CASES) >= 50, f'expected >=50 samples, got {len(CASES)}'
    assert len(REFUSE_CASES) >= 20
    assert len(TRANSFER_CASES) >= 20


@pytest.mark.parametrize('cid,seed,replay,_allow', REFUSE_CASES, ids=[c[0] for c in REFUSE_CASES])
def test_no_leak(cid: str, seed: Obs, replay: Obs, _allow: bool) -> None:
    """No must-refuse page may be ALLOWED. ABSTAIN is acceptable (escalates to LLM)."""
    d = decide(seed, replay)
    assert d.verdict is not Verdict.ALLOW, f'LEAK on {cid}: rule={d.rule} reason={d.reason}'


@pytest.mark.parametrize('cid,seed,replay,_allow', TRANSFER_CASES, ids=[c[0] for c in TRANSFER_CASES])
def test_transfer_not_refused(cid: str, seed: Obs, replay: Obs, _allow: bool) -> None:
    """A must-transfer page must not be hard-REFUSED (ALLOW or ABSTAIN both ok)."""
    d = decide(seed, replay)
    assert d.verdict is not Verdict.REFUSE, f'false refuse on {cid}: rule={d.rule} reason={d.reason}'


def test_aggregate_leak_and_false_alarm_budget() -> None:
    """Headline gate: leaks == 0; false alarms within budget. Leaks are the sin."""
    leaks = fa = 0
    for cid, seed, replay, should_allow in CASES:
        d = decide(seed, replay)
        if not should_allow and d.verdict is Verdict.ALLOW:
            leaks += 1
        if should_allow and d.verdict is Verdict.REFUSE:
            fa += 1
    assert leaks <= MAX_LEAKS, f'{leaks} leaks (budget {MAX_LEAKS})'
    assert fa <= MAX_FALSE_ALARMS, f'{fa} false alarms (budget {MAX_FALSE_ALARMS})'


def test_costume_case_caught() -> None:
    """Pin the case no numeric guard could catch: reddit /user/spez must refuse."""
    spez = next((c for c in REFUSE_CASES if 'spez' in c[0]), None)
    assert spez is not None, 'costume fixture missing'
    d = decide(spez[1], spez[2])
    assert d.verdict is Verdict.REFUSE, f'costume case regressed: {d}'


def test_abstain_rate_economics() -> None:
    """Abstain = a paid LLM call. Keep it low or the cost model breaks."""
    abstains = sum(1 for _c, s, r, _a in CASES if decide(s, r).verdict is Verdict.ABSTAIN)
    rate = abstains / len(CASES)
    assert rate <= 0.25, f'abstain rate {rate:.0%} too high; LLM cost model breaks'
