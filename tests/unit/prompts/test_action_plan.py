"""Tests for the action-plan discovery prompt module.

Doesn't invoke the LLM — verifies the prompt-building helpers wire together
correctly and surface the agent's primitive vocabulary.
"""

from __future__ import annotations

from yosoi.prompts.action_plan import (
    ActionPlanDiscoveryDeps,
    action_plan_base_instructions,
    action_plan_intent_instructions,
    action_plan_primitives_guide,
    build_action_plan_user_prompt,
    trim_for_action_plan,
)


class _FakeContext:
    """Minimal RunContext stand-in: the prompt functions only touch ``ctx.deps``."""

    def __init__(self, deps: ActionPlanDiscoveryDeps) -> None:
        self.deps = deps


def _make_deps(intent: str = 'load every public comment on the post') -> ActionPlanDiscoveryDeps:
    return ActionPlanDiscoveryDeps(
        target='reddit.com/r/ted/post',
        intent=intent,
        html='<html><body><faceplate-partial src="/more-comments/..."><button>View more</button></faceplate-partial></body></html>',
    )


def test_base_instructions_warn_against_inventing_selectors() -> None:
    ctx = _FakeContext(_make_deps())
    text = action_plan_base_instructions(ctx)  # type: ignore[arg-type]
    assert 'never invent selectors' in text
    # Empty plan is a valid answer — discourages "always click something".
    assert 'empty list' in text.lower()


def test_intent_instructions_quote_the_intent_verbatim() -> None:
    intent = 'open every collapsed thread'
    ctx = _FakeContext(_make_deps(intent=intent))
    text = action_plan_intent_instructions(ctx)  # type: ignore[arg-type]
    assert intent in text


def test_primitives_guide_covers_click_until_and_selector_absent() -> None:
    ctx = _FakeContext(_make_deps())
    text = action_plan_primitives_guide(ctx)  # type: ignore[arg-type]
    # Both are critical to reddit-style lazy pagination — they MUST be taught.
    assert 'click_until' in text
    assert 'selector_absent' in text
    # The structural-vs-count termination rationale should be present so the
    # LLM doesn't reach for min_count and trip on skeleton placeholders.
    assert 'skeleton' in text.lower()


def test_user_prompt_runs_html_through_trimmer() -> None:
    """The user prompt sends the TRIMMED html, not the raw HTML — saves token cost."""
    deps = _make_deps()
    prompt = build_action_plan_user_prompt(deps)
    # The faceplate-partial element + its 'View more' trigger must survive.
    assert 'faceplate-partial' in prompt
    assert 'View more' in prompt
    assert 'Rendered HTML' in prompt


# ---------------------------------------------------------------------------
# trim_for_action_plan — the HTML diet
# ---------------------------------------------------------------------------


def test_trimmer_strips_script_style_svg_meta() -> None:
    html = """
    <html>
      <head>
        <meta charset='utf-8'>
        <link rel='stylesheet' href='/x.css'>
        <style>.a { color: red }</style>
        <script>window.x = 1</script>
      </head>
      <body>
        <svg><path d='M0 0'/></svg>
        <button class='load-more'>View more</button>
      </body>
    </html>
    """
    out = trim_for_action_plan(html)
    assert 'window.x' not in out
    assert 'color: red' not in out
    assert '<svg' not in out
    assert '<meta' not in out
    # The trigger survives — that's the WHOLE POINT.
    assert 'View more' in out


def test_trimmer_preserves_custom_element_triggers() -> None:
    """Reddit's `<faceplate-partial src=more-comments>` is the canonical hard case
    — a custom element with a key attribute. Both must survive."""
    html = """
    <html><body>
      <article>
        <p>An ordinary post, lots of content here that the agent doesn't care about for
        action-plan discovery. The script just needs to know whether load-more triggers
        exist below.</p>
      </article>
      <faceplate-partial src="/svc/shreddit/more-comments/abc">
        <button>View 12 more replies</button>
      </faceplate-partial>
    </body></html>
    """
    out = trim_for_action_plan(html)
    assert 'faceplate-partial' in out
    assert 'more-comments' in out
    assert 'View 12 more replies' in out


def test_trimmer_truncates_bulk_text_outside_triggers() -> None:
    """Non-trigger leaf text > 80 chars gets ellipsised — that's where the bytes
    savings come from on real pages (comment bodies, article text)."""
    long_body = 'x' * 5_000
    html = f'<html><body><div class="post"><p>{long_body}</p></div></body></html>'
    out = trim_for_action_plan(html)
    assert long_body not in out
    assert '…' in out  # truncation marker


def test_trimmer_obeys_hard_cap() -> None:
    """If the post-trim output is still > hard_cap, slice the tail and annotate."""
    # A page that mostly looks like triggers (so per-tag shortening doesn't help)
    # — many distinct buttons, each with a short label.
    body = ''.join(f'<button>load page {i}</button>' for i in range(20_000))
    html = f'<html><body>{body}</body></html>'
    out = trim_for_action_plan(html, hard_cap=10_000)
    assert len(out) <= 10_000 + 100  # cap + trim-annotation
    assert 'trimmed' in out


def test_trimmer_passes_small_clean_html_through_mostly_untouched() -> None:
    html = '<html><body><h1>title</h1><button class="x">Load more</button></body></html>'
    out = trim_for_action_plan(html)
    assert 'title' in out
    assert 'Load more' in out
