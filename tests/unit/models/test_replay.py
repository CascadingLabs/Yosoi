"""Tests for replay and discovery lesson contracts."""

from datetime import datetime, timezone

import pytest

from yosoi.models.replay import (
    ActKind,
    AssertKind,
    DiscoveryLesson,
    LessonKey,
    LessonValidation,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
    ReplayStatus,
    VerifyReport,
)
from yosoi.models.selectors import css, role, visual
from yosoi.models.snapshot import SelectorSnapshot


class TestReplayAct:
    def test_navigate_requires_url(self):
        with pytest.raises(ValueError, match='navigate acts require url'):
            ReplayAct(kind=ActKind.NAVIGATE)

    def test_click_requires_target(self):
        with pytest.raises(ValueError, match='click acts require at least one target'):
            ReplayAct(kind=ActKind.CLICK)

    def test_click_accepts_selector_cascade(self):
        act = ReplayAct(kind=ActKind.CLICK, targets=[role('button', 'More'), css('button.more')])
        assert [target.type for target in act.targets] == ['role', 'css']

    def test_visual_target_is_serializable(self):
        act = ReplayAct(kind=ActKind.CLICK, targets=[visual(10, 20)])
        restored = ReplayAct.model_validate(act.model_dump(mode='json'))
        assert restored.targets[0].type == 'visual'
        assert restored.targets[0].x == 10


class TestReplayPlan:
    def test_empty_plan(self):
        assert ReplayPlan().is_empty is True

    def test_plan_round_trip(self):
        node = ReplayNode(
            id='click-more',
            intent='open more results',
            assess=ReplayCondition(kind=AssertKind.SELECTOR, selector=css('main')),
            act=ReplayAct(kind=ActKind.CLICK, targets=[role('button', 'More')]),
            expect=ReplayCondition(kind=AssertKind.COUNT, selector=css('article'), value=10),
        )
        plan = ReplayPlan(nodes=[node])

        restored = ReplayPlan.model_validate(plan.model_dump(mode='json'))

        assert restored.is_empty is False
        assert restored.nodes[0].act.targets[0].type == 'role'


class TestVerifyReport:
    def test_empty_report_scores_one(self):
        assert VerifyReport().score == 1.0

    def test_score(self):
        assert VerifyReport(passed=3, failed=1).score == 0.75


class TestDiscoveryLesson:
    def test_lesson_key_storage_key_is_filesystem_safe(self):
        key = LessonKey(domain='news.ycombinator.com', contract_signature='abc/123', page_profile='top stories')
        assert key.storage_key == 'news_ycombinator_com__abc_123__top_stories__mcp'

    def test_per_engine_key_has_distinct_namespace(self):
        # An engine-keyed lesson (the hotpath inversion) must not collide with a
        # domain-keyed lesson for the same contract: the 'engine_' prefix + the
        # param-keys segment keep the two namespaces disjoint.
        engine = LessonKey(
            domain='ignored',
            contract_signature='sig',
            engine_host='similarweb.com',
            param_keys=('d',),
        )
        per_domain = LessonKey(domain='ignored', contract_signature='sig')
        assert engine.storage_key == 'engine_similarweb_com__sig__d__default__mcp'
        assert engine.storage_key != per_domain.storage_key

    def test_per_destination_key_unchanged_when_no_engine_host(self):
        # Backward compatibility: adding engine_host/param_keys must not perturb
        # the legacy per-destination storage_key format.
        key = LessonKey(domain='example.com', contract_signature='sig')
        assert key.storage_key == 'example_com__sig__default__mcp'

    def test_active_requires_status_and_validation(self):
        now = datetime.now(timezone.utc)
        lesson = DiscoveryLesson(
            key=LessonKey(domain='example.com', contract_signature='sig'),
            replay_plan=ReplayPlan(),
            selectors={'title': SelectorSnapshot(primary='h1', discovered_at=now)},
            validation=LessonValidation(report=VerifyReport(passed=1), threshold=1.0),
        )
        assert lesson.is_active is True

        lesson.status = ReplayStatus.STALE
        assert lesson.is_active is False

    def test_validation_threshold(self):
        validation = LessonValidation(report=VerifyReport(passed=3, failed=1), threshold=0.8)
        assert validation.passed is False


# ---------------------------------------------------------------------------
# ReplayAct validator — missing branches (lines 84, 86)
# ---------------------------------------------------------------------------


def test_type_act_without_text_raises():
    """TYPE act requires non-None text (line 84)."""
    from pydantic import ValidationError

    from yosoi.models.replay import ActKind, ReplayAct
    from yosoi.models.selectors import css

    with pytest.raises(ValidationError, match='type acts require'):
        ReplayAct(kind=ActKind.TYPE, targets=[css('input')], text=None)


def test_eval_act_without_script_raises():
    """EVAL act requires a non-empty script (line 86)."""
    from pydantic import ValidationError

    from yosoi.models.replay import ActKind, ReplayAct

    with pytest.raises(ValidationError, match='eval acts require'):
        ReplayAct(kind=ActKind.EVAL, script=None)
