"""Tests for ActionPlanStorage — LLM-discovered ReplayPlan persistence."""

from __future__ import annotations

from pathlib import Path

from yosoi.models.replay import ReplayPlan, click_until, css, selector_absent
from yosoi.storage.action_plan import ActionPlanStorage, _slug


def _make_plan(target: str = 'reddit.com/r/ted/post') -> ReplayPlan:
    """Build a representative reddit-style plan with click_until + selector_absent."""
    load_more = css('faceplate-partial[src*="more-comments"] button')
    return ReplayPlan(
        target=target,
        task='load every public comment on the post',
        source='scripted',
        nodes=[
            click_until(
                load_more,
                expect=selector_absent(css('faceplate-partial[src*="more-comments"]')),
                max_iters=40,
                intent='expand every more-comments partial until none remain',
            ),
        ],
    )


def test_slug_normalises_path_and_scheme(tmp_path: Path) -> None:
    assert _slug('reddit.com/r/ted/post') == 'reddit.com_r_ted_post'
    # https:// → https__ (one `_` for the colon's gap, two from the `//`).
    # Determinism matters more than aesthetics; targets never contain `_` to
    # begin with in practice, so consecutive underscores are unambiguous.
    assert _slug('https://example.com') == 'https__example.com'
    assert _slug('') == 'default'


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    storage = ActionPlanStorage(storage_dir=tmp_path)
    plan = _make_plan()
    path = storage.save(plan)

    assert path.exists()
    assert path.parent == tmp_path

    loaded = storage.load(plan.target)
    assert loaded is not None
    assert loaded.target == plan.target
    assert loaded.task == plan.task
    assert len(loaded.nodes) == 1
    node = loaded.nodes[0]
    # The click_until shape — repeat, max_iters, click op, structural termination
    assert getattr(node, 'repeat', False) is True
    assert getattr(node, 'max_iters', 0) == 40
    assert node.act.op == 'click'  # type: ignore[union-attr]
    assert node.expect is not None  # type: ignore[union-attr]
    assert node.expect.kind == 'selector_absent'  # type: ignore[union-attr]


def test_load_returns_none_for_missing_target(tmp_path: Path) -> None:
    storage = ActionPlanStorage(storage_dir=tmp_path)
    assert storage.load('never-saved') is None


def test_has_reflects_save_and_delete(tmp_path: Path) -> None:
    storage = ActionPlanStorage(storage_dir=tmp_path)
    plan = _make_plan()
    assert not storage.has(plan.target)

    storage.save(plan)
    assert storage.has(plan.target)

    removed = storage.delete(plan.target)
    assert removed is True
    assert not storage.has(plan.target)

    # Idempotent: deleting again returns False, no error
    assert storage.delete(plan.target) is False


def test_malformed_file_is_cache_miss_not_exception(tmp_path: Path) -> None:
    storage = ActionPlanStorage(storage_dir=tmp_path)
    # Write a file at the path the loader would look for; not valid JSON for ReplayPlan.
    target = 'broken.example/path'
    (tmp_path / f'plan_{_slug(target)}.json').write_text('{not valid json', encoding='utf-8')
    assert storage.load(target) is None


def test_per_target_isolation(tmp_path: Path) -> None:
    storage = ActionPlanStorage(storage_dir=tmp_path)
    storage.save(_make_plan('reddit.com/r/ted/post'))
    storage.save(_make_plan('reddit.com/r/python/post'))

    a = storage.load('reddit.com/r/ted/post')
    b = storage.load('reddit.com/r/python/post')
    assert a is not None
    assert b is not None
    assert a.target != b.target
