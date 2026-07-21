# yosoi: allow-hardcoded-selectors -- non-canonical API sketch; selectors illustrate authoring shape only.
"""Experimental, non-canonical Google Maps Executor.js and Flow example.

The compact API in this file is wired into Yosoi and runnable, but remains an
experiments surface rather than a compatibility promise. It deliberately starts
with the deterministic A3 primitives already supported by the replay runtime.

The design separates three concerns currently mixed together in ``reviews.py``:

1. Browser flows mutate page state: click, sort, scroll, expand, open, and close.
2. JavaScript modules read typed values from the resulting page state.
3. Python contracts validate and normalize those returned values.

An evaluator should be a deterministic value producer, not an unstructured
container for an entire browser workflow.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel

import yosoi as ys
from examples.google_maps.google_maps import build_maps_search_url

# -----------------------------------------------------------------------------
# Proposed local JavaScript module tree
# -----------------------------------------------------------------------------
#
# The source lives beside this spec instead of inside 100-line Python strings:
#
#   google_maps/
#   ├── api_spec_maps.py
#   └── _js_helpers/
#       ├── place/
#       │   ├── index.mjs
#       │   └── schedule.mjs
#       └── reviews/
#           ├── index.mjs
#           ├── canonical_cards.mjs
#           ├── extract_cards.mjs
#           └── share_dialog.mjs
#
# ``Executor.js.modules`` resolves paths relative to an explicit root, exposes
# named ESM exports as immutable function handles, and bundles each export's
# transitive relative imports before browser evaluation. The browser never receives
# a local filesystem path and never performs an import.
#
# Proposed safety/portability rules:
# - Only files below ``root`` may be loaded; ``..`` traversal is rejected.
# - Start with static relative ``.js``/``.mjs`` imports only. No network or dynamic
#   imports, Node built-ins, package resolution, or filesystem access.
# - The full transitive source graph and selected export enter the fingerprint.
# - Recipes vendor the source graph or deterministic bundle; they never retain an
#   arbitrary path into the author's machine.
# - Runtime errors retain module, export, source location, field, and flow position.
# - Development can reload changed files; a compiled recipe pins content hashes.
#
# The current implementation intentionally supports only a tiny static ESM subset:
# named function exports plus static relative named imports/re-exports.

# ``Executor.js`` is a small callable namespace: calling it creates an executor
# descriptor; ``.modules(...)`` loads a local ESM graph. One name covers the JS
# execution concept without growing separate ``javascript`` and ``eval_js`` APIs.
MAPS_JAVASCRIPT = ys.Executor.js.modules(root=Path(__file__).with_name('_js_helpers'))

extract_schedule = MAPS_JAVASCRIPT.function('place/index.mjs', export='extractSchedule')
extract_review_cards = MAPS_JAVASCRIPT.function('reviews/index.mjs', export='extractReviewCards')
read_share_url = MAPS_JAVASCRIPT.function('reviews/index.mjs', export='readShareUrl')


# -----------------------------------------------------------------------------
# Experimental primitive: ys.Executor.js
# -----------------------------------------------------------------------------
#
# This is the brief, discoverable spelling of ``ys.js(script=...)``. ``ys.js``
# remains compatible while this API is exercised on live sites.
#
# ``Executor.js(...)`` returns one immutable descriptor. A Contract contextualizes
# it as a typed field producer; an A3 ``Node`` contextualizes it as an EVAL act.
# That keeps one JS execution concept without maintaining two subtly different
# evaluator APIs.
#
# Desired guarantees:
# - The contract annotation is the output schema. There is no competing ``parse=``.
# - ``scope='page'`` is explicit; page values are not silently broadcast to rows.
# - Arguments are JSON-bound. Python never interpolates values into source.
# - Flow EVAL exceptions fail loudly. Contract fields retain current ys.js batch
#   isolation, where an exception becomes null before annotation validation.
# - There is no per-call ``on_error`` escape hatch in the experimental API.
# - Readiness/settling is separate from execution and remains observable.
# - The function graph, arguments, output type, and scope enter the fingerprint.
#
# Discovery could eventually produce the same JavaScriptFunction artifact:
#
#     ys.Executor.js(
#         description='Extract regular weekly hours from the primary place panel',
#         scope='page',
#     )


class Schedule(ys.Contract):
    """Regular hours returned as one typed evaluator value."""

    timezone: str | None = None
    days: dict[str, str | None]


class GoogleMapsPlace(ys.Contract):
    """The exact business shown in the primary Google Maps detail panel."""

    name: str = ys.Title(description='Name in the primary business detail panel')
    rating: float = ys.Rating(
        as_float=True,
        description='Star rating for the primary business, excluding nearby places',
    )
    review_count: int = ys.Field(
        description='Total review count adjacent to the primary business rating, excluding nearby places'
    )
    address: str = ys.Field(description='Listed address in the primary business detail panel')
    phone: str | None = ys.Field(
        default=None,
        description='Published phone number, or none when the primary panel omits it',
    )
    website: str | None = ys.Url(
        default=None,
        strip_tracking=True,
        description='Business website destination, excluding Google Maps links',
    )
    plus_code: str = ys.Field(description='Plus Code published by the primary business panel')

    # Today the closest spelling is ``ys.js(script=Path(...).read_text())``.
    # A function handle gives us named exports, dependency fingerprints, recipe
    # portability, and useful source locations without embedding source here.
    schedule: Schedule | None = ys.Executor.js(
        extract_schedule,
        scope='page',
        settle=ys.until.non_null(timeout=8, poll_interval=0.25),
        description='Regular weekly hours from the primary business panel',
        default=None,
    )


class GoogleMapsReview(BaseModel):
    """One review extracted from the canonical rendered review card."""

    review_id: str
    sample_rank: int
    rating: float
    review_text: str | None = None
    relative_date: str
    reviewer_name: str
    reviewer_profile_url: str | None = None
    contribution_label: str | None = None
    owner_response_text: str | None = None
    owner_response_relative_date: str | None = None

    # This is populated by the optional, stateful enrichment phase below. It is
    # deliberately not hidden inside the pure review-card evaluator.
    # Exact share URLs require the optional serial dialog-enrichment phase, which
    # is intentionally not part of the first runnable Flow implementation.
    review_url: str | None = None


class GoogleMapsReviewPage(BaseModel):
    """Validated output assembled from the runnable review Flow."""

    reviews: list[GoogleMapsReview]


# -----------------------------------------------------------------------------
# Browser flows are manually-authored A3Node programs
# -----------------------------------------------------------------------------
#
# ``Flow`` should not be a second browser automation model. It is the declarative
# class spelling of the existing A3Node ReplayPlan/tree:
#
# - class-definition order is sequence order;
# - each public attribute lowers to one assess / act / expect ReplayNode;
# - the attribute name becomes the stable node id (``open_reviews``);
# - intent defaults to the humanized id;
# - ``Flow.compile`` produces the same ReplayPlan shape as discovered A3Nodes;
# - both execute through the same deterministic runtime.
#
# A small metaclass, like Contract, captures declaration order and inheritance.
# Enum cannot carry ordered parameterized acts; dataclasses remain useful for the
# compiled node models rather than the authoring surface.
#
# Target descriptions are positional to their act. ``target=ys.target(...)`` says
# the same thing three times. ``ys.click(ys.role(...))`` is enough.
#
# The annotation is the A3 expectation, just as a Contract annotation is the output
# schema and its assigned Field describes acquisition. A named ``State`` contains a
# selector or richer condition; ``Expect[ThatState]`` lowers to ReplayNode.expect.
#
# An ordinary annotation on ``Executor.js`` is instead its captured output type.
# The attribute name becomes both node id and output field, so ``review_url: str``
# needs no separate ``output='review_url'`` declaration.
#
# ``scroll_until`` and ``click_all`` remain compile-time A3 macros. Scroll lowers
# to a repeated SCROLL with a COUNT assertion; click_all lowers to one bounded CLICK
# over row scopes. Both execute through the existing A3 dispatch path.


REVIEW_CARD = ys.css('[data-review-id]')
# AX matching is case-insensitive substring matching, so "More" also matches the
# current "See more" accessible name without a fallback target list.
MORE_REVIEW_TEXT = ys.role('button', name='More')


class ReviewsTabReady(ys.State):
    condition = ys.role('tab', name='Reviews')


class SortButtonReady(ys.State):
    condition = ys.role('button', name='Sort reviews')


class SortMenuReady(ys.State):
    condition = ys.css('[role="menuitemradio"]')


class SortSettled(ys.State):
    condition = ys.dom_stable(quiet_ms=300)


class ReviewLimitLoaded(ys.State):
    condition = ys.count(REVIEW_CARD, at_least=ys.input('limit'))


class PrepareReviews(ys.Flow):
    """Reveal a bounded, sorted set of complete review cards."""

    reviews_ready: ys.Expect[ReviewsTabReady] = ys.wait_until(
        max_attempts=20,
        interval_ms=250,
    )

    open_reviews: ys.Expect[SortButtonReady] = ys.click(ys.role('tab', name=ys.matches(r'\bReviews\b')))

    open_sort_menu: ys.Expect[SortMenuReady] = ys.click(ys.role('button', name='Sort reviews'))

    choose_sort: ys.Expect[SortSettled] = ys.click(ys.role('menuitemradio', name='Newest'))

    load_reviews: ys.Expect[ReviewLimitLoaded] = ys.scroll_until(
        ys.nearest_scroll_parent(REVIEW_CARD),
        max_scrolls=ys.input('max_scrolls'),
        stop_when='no_growth',
    )

    expand_reviews = ys.click_all(
        MORE_REVIEW_TEXT,
        within=REVIEW_CARD,
        limit=ys.input('limit'),
    )


# A Flow may still spell out ``ys.Node(assess=..., act=..., expect=...)`` when the
# convenience act does not communicate enough. The compact declarations above are
# constructors for that exact node shape, not a looser imperative API.


class GoogleMapsReviews(PrepareReviews):
    """Prepare the panel, then capture and validate one page-scoped review list."""

    reviews: list[GoogleMapsReview] = ys.Executor.js(
        extract_review_cards,
        args={'limit': ys.input('limit')},
        settle=ys.until.length_at_least(1, timeout=10, poll_interval=0.25),
    )


async def example_usage(
    url: str,
    *,
    limit: int = 20,
    fetcher_type: str = 'headless',
) -> GoogleMapsReviewPage:
    """Execute the handwritten A3 flow through a live VoidCrawl browser."""
    if not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    result = await GoogleMapsReviews.run(
        url,
        inputs={'limit': limit, 'max_scrolls': (limit // 5) + 5},
        fetcher_type=fetcher_type,
        timeout=45,
        quiet=False,
        warmup=2,
    )
    return GoogleMapsReviewPage.model_validate(result.values)


def parse_args() -> argparse.Namespace:
    """Parse the runnable live example options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business', default='Six Flags Over Georgia')
    parser.add_argument('--location', default='Austell, GA')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--fetcher', choices=('headless', 'headful'), default='headless')
    return parser.parse_args()


async def main() -> None:
    """Run the live Flow and display its validated output."""
    args = parse_args()
    url = build_maps_search_url(f'{args.business}, {args.location}')
    page = await example_usage(url, limit=args.limit, fetcher_type=args.fetcher)
    ys.show(page.model_dump(mode='json'))


if __name__ == '__main__':
    asyncio.run(main())


# -----------------------------------------------------------------------------
# What this would normalize
# -----------------------------------------------------------------------------
#
# - ``google_maps.py`` can return one nested Schedule value instead of maintaining
#   seven selector-oriented weekday fields and hiding them behind a serializer.
# - ``reviews.py`` becomes a flow plus typed modules rather than repeated eval text.
# - Shared JS helpers are testable with ordinary JavaScript tooling in isolation.
# - ``stress_test.py`` can execute these contracts instead of maintaining a second
#   regex extraction system that can drift from production behavior.
# - Browser selection, pool lifecycle, and warm-up move behind one public boundary.
#
# Open questions before canonizing anything:
#
# 1. Is contextualizing one ``ys.Executor.js`` descriptor in both Contract fields
#    and A3 Nodes worth the metaclass work, or should Nodes require ``ys.eval``?
# 2. Should Flow class attributes accept only leaf-node descriptors, or also nested
#    Sequence/Selector/Reaction composites? They should compile to existing TreeNode
#    kinds rather than inventing another control-flow representation.
# 3. Does the deliberately tiny static ESM subset cover enough real contracts, or
#    should recipe compilation eventually use a dedicated deterministic bundler?
# 4. Should source modules be recipe assets, or should recipes retain only a bundle
#    plus source map? Keeping both improves reviewability and diagnostics.
# 5. Should page-scoped fields be forbidden on rooted multi-row contracts unless the
#    author explicitly opts into broadcasting?
# 6. Should share-URL enrichment fail the whole sample or produce a separately typed
#    partial result? Yosoi's default should remain fail-fast.
# 7. How much intent should Flow infer from attribute names? ``open_reviews`` is a
#    useful stable id, but recipes may still benefit from an explicit human intent.
