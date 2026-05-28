"""Tests for the canonical replay schema (A3Node primitive + composition + verify)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.models.replay import (
    A3Node,
    AgentAnnotations,
    Assertion,
    NodeResult,
    Parallel,
    ReplayPlan,
    SelectorEntry,
    StepAnnotation,
    VerifyReport,
    click,
    click_until,
    css,
    fill,
    merge_annotations,
    min_count,
    navigate,
    parallel,
    role,
    scroll_until,
    selector_absent,
    teleport,
    visual,
    wait,
)


def test_selector_entry_validates_per_type() -> None:
    with pytest.raises(ValidationError):
        SelectorEntry(type='role')  # needs role
    with pytest.raises(ValidationError):
        SelectorEntry(type='css')  # needs a non-empty value
    with pytest.raises(ValidationError):
        SelectorEntry(type='visual', x=1.0)  # needs y too
    assert role('button', 'Load more').role == 'button'
    assert css('.more').value == '.more'
    assert visual(10, 20).type == 'visual'


def test_selectorentry_identity_distinguishes_role_from_value() -> None:
    # role selectors have empty value; identity must use role/name, not value.
    assert role('button', 'A').key() != role('button', 'B').key()
    assert css('.x').key() != css('.y').key()


def test_builders_compose_a3node_primitive() -> None:
    nav = navigate('https://x.test', expect=Assertion(kind='url_contains', text='x.test'))
    assert nav.act.op == 'navigate'
    assert nav.expect is not None

    tp = teleport(40.7, -74.0, 'America/New_York')
    assert tp.act.op == 'teleport'
    assert tp.act.lat == 40.7
    assert tp.act.timezone == 'America/New_York'

    # fallback cascade preserved in order
    c = click(role('button', 'Load more'), css('.more'), expect=min_count(20))
    assert [t.type for t in c.act.targets] == ['role', 'css']
    assert c.expect == min_count(20)

    sc = scroll_until('div[role="feed"]', 'a.hfpxzc', 20)
    assert sc.repeat is True
    assert sc.max_iters == 15
    assert sc.expect == min_count(20)


def test_a3node_round_trips() -> None:
    node = click(role('button', 'Go'), expect=min_count(1), intent='advance')
    again = A3Node.model_validate_json(node.model_dump_json())
    assert again.expect == node.expect
    assert again.intent == 'advance'
    assert again.act.op == 'click'


def test_merge_annotations_folds_intent_and_expect_by_index() -> None:
    nodes = [navigate('https://x.test'), click(role('button', 'Go'))]
    anns = [StepAnnotation(step=1, intent='load results', expect=min_count(20))]
    merge_annotations(nodes, anns)
    assert nodes[0].intent is None  # untouched
    assert nodes[1].intent == 'load results'
    assert nodes[1].expect == min_count(20)


def test_agent_annotations_output_schema_is_generatable() -> None:
    # Used as a pydantic-ai output_type, so its JSON schema must build cleanly.
    schema = AgentAnnotations.model_json_schema()
    assert 'annotations' in schema['properties']


def test_replay_plan_round_trips() -> None:
    plan = ReplayPlan(
        target='google.com/maps',
        task='guitar shops near me',
        nodes=[teleport(40.7, -74.0), scroll_until('div[role="feed"]', 'a.hfpxzc', 20)],
        source='mcp-agent',
    )
    again = ReplayPlan.model_validate_json(plan.model_dump_json())
    assert again.nodes[1].repeat is True
    assert again.source == 'mcp-agent'


def test_parallel_group_round_trip() -> None:
    plan = ReplayPlan(
        target='x',
        task='t',
        nodes=[navigate('https://x.test'), parallel(fill('input#a', '1'), fill('input#b', '2'))],
    )
    again = ReplayPlan.model_validate_json(plan.model_dump_json())
    n0 = again.nodes[0]
    assert isinstance(n0, A3Node)  # A3Node arm (structural smart union)
    assert n0.act.op == 'navigate'
    n1 = again.nodes[1]
    assert isinstance(n1, Parallel)  # Parallel arm — distinguished by having `nodes`
    assert len(n1.nodes) == 2


def test_wait_node_carries_fixed_seconds() -> None:
    w = wait(3.0, intent='let geo settle')
    assert w.act.op == 'wait'
    assert w.act.seconds == 3.0
    again = A3Node.model_validate_json(w.model_dump_json())
    assert again.act.seconds == 3.0


def test_selector_absent_is_the_twin_of_selector_present() -> None:
    """`selector_absent` is the structural 'done' condition — termination for lazy
    pagination when 'count' would falsely pass on skeleton placeholders."""
    sel = css('faceplate-partial[src*="more-comments"]')
    a = selector_absent(sel)
    assert a.kind == 'selector_absent'
    assert a.selector == sel
    again = Assertion.model_validate_json(a.model_dump_json())
    assert again.kind == 'selector_absent'
    assert again.selector == sel


def test_click_until_is_a_repeating_click_node() -> None:
    """click_until is the load-more / pagination twin of scroll_until: repeat=True,
    same fallback cascade as click, and an expect that drives termination."""
    target = min_count(13, css('shreddit-comment'))
    node = click_until(
        css('faceplate-partial[src*="more-comments"] button'),
        expect=target,
        max_iters=30,
        intent='expand all collapsed threads',
    )
    assert node.act.op == 'click'
    assert node.repeat is True
    assert node.max_iters == 30
    assert node.expect == target
    assert node.intent == 'expand all collapsed threads'
    again = A3Node.model_validate_json(node.model_dump_json())
    assert again.repeat is True
    assert again.max_iters == 30
    assert again.expect == target


def test_min_count_carries_optional_selector() -> None:
    bare = min_count(20)
    assert bare.count == 20
    assert bare.selector is None
    scoped = min_count(8, css('a.hfpxzc'))
    assert scoped.count == 8
    assert scoped.selector is not None
    assert scoped.selector.value == 'a.hfpxzc'


def test_verify_report_scores_pass_rate() -> None:
    report = VerifyReport(
        results=[
            NodeResult(index=0, op='teleport', passed=True),
            NodeResult(index=1, op='navigate', passed=True),
            NodeResult(index=2, op='scroll', passed=False, detail='8 < 20'),
        ]
    )
    assert report.score == pytest.approx(2 / 3)
    assert report.ok is False
    assert [r.index for r in report.failures] == [2]
