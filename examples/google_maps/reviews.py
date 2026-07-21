# yosoi: allow-hardcoded-selectors -- site-specific review workflow probes public Google Maps review cards.
"""Extract a bounded Google Maps review sample with full text and per-review URLs.

The workflow uses one anonymous VoidCrawl browser pool, opens the Reviews tab,
loads at most 100 unique reviews, expands truncated text, and reads each review's
public Share-review URL without writing to the clipboard.

Run:
    uv run python examples/google_maps/reviews.py
    uv run python examples/google_maps/reviews.py --sort newest --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator
from rich.console import Console
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from examples.google_maps.google_maps import build_maps_search_url
from yosoi.core.fetcher.voiddriver import HeadfulFetcher, HeadlessFetcher

DEFAULT_OUTPUT = Path('.yosoi/google-maps/reviews.json')
MAX_REVIEWS = 100
SortMode = Literal['relevant', 'newest', 'highest', 'lowest']
FetcherType = Literal['headless', 'headful']
SORT_LABELS: dict[SortMode, str] = {
    'relevant': 'Most relevant',
    'newest': 'Newest',
    'highest': 'Highest rating',
    'lowest': 'Lowest rating',
}


class GoogleMapsReview(BaseModel):
    """One public Google Maps review and its provenance."""

    review_id: str = Field(min_length=1)
    review_url: str = Field(min_length=1)
    sample_rank: int = Field(ge=1)
    sort_mode: SortMode
    rating: float = Field(ge=1, le=5)
    review_text: str | None = None
    relative_date: str = Field(min_length=1)
    reviewer_name: str = Field(min_length=1)
    reviewer_id: str | None = None
    reviewer_profile_url: str | None = None
    reviewer_reviews_count: int | None = Field(default=None, ge=0)
    reviewer_photos_count: int | None = Field(default=None, ge=0)
    local_guide: bool = False
    owner_response_text: str | None = None
    owner_response_relative_date: str | None = None

    @field_validator('review_url')
    @classmethod
    def validate_review_url(cls, value: str) -> str:
        """Require the exact public short-link shape returned by Google's Share-review dialog."""
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.netloc != 'maps.app.goo.gl' or not parsed.path.strip('/'):
            raise ValueError('review URL must be a Google Maps HTTPS share URL')
        return value


class GoogleMapsReviewSample(BaseModel):
    """Bounded review sample plus acquisition metadata needed by downstream analysis."""

    business: str = Field(min_length=1)
    location: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    sort_mode: SortMode
    requested_limit: int = Field(ge=1, le=MAX_REVIEWS)
    retrieved_count: int = Field(ge=0, le=MAX_REVIEWS)
    captured_at: datetime
    reviews: list[GoogleMapsReview]

    @field_validator('captured_at')
    @classmethod
    def require_aware_capture_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError('capture timestamp must include a timezone')
        return value

    @model_validator(mode='after')
    def validate_sample_consistency(self) -> GoogleMapsReviewSample:
        if self.retrieved_count != len(self.reviews):
            raise ValueError('retrieved count must equal the number of reviews')
        if self.retrieved_count > self.requested_limit:
            raise ValueError('retrieved count must not exceed the requested limit')
        if [review.sample_rank for review in self.reviews] != list(range(1, len(self.reviews) + 1)):
            raise ValueError('review sample ranks must be contiguous and ordered')
        if any(review.sort_mode != self.sort_mode for review in self.reviews):
            raise ValueError('every review sort mode must match its sample')
        return self


class _ReviewsNotLoaded(RuntimeError):
    """The rendered review count has not increased yet."""


class _SortMenuNotReady(RuntimeError):
    """The asynchronous review-sort menu has not rendered its options yet."""


class _ReviewsNotExpanded(RuntimeError):
    """One or more truncated review bodies have not expanded yet."""


class _ReviewMenuNotReady(RuntimeError):
    """A review's asynchronous action menu has not rendered yet."""


class _ShareDialogNotReady(RuntimeError):
    """The Share-review dialog has not exposed its URL yet."""


def _bounded_limit(value: str) -> int:
    limit = int(value)
    if not 1 <= limit <= MAX_REVIEWS:
        raise argparse.ArgumentTypeError(f'limit must be between 1 and {MAX_REVIEWS}')
    return limit


def _count_from_label(label: str | None, noun: str) -> int | None:
    if not label:
        return None
    match = re.search(rf'([\d,]+)\s+{noun}', label, re.IGNORECASE)
    return int(match.group(1).replace(',', '')) if match else None


def _reviewer_id(profile_url: str | None) -> str | None:
    if not profile_url:
        return None
    match = re.search(r'/maps/contrib/(\d+)', profile_url)
    return match.group(1) if match else None


async def _settle(tab: Any) -> None:
    try:
        await tab.wait_for_network_idle(timeout=10.0)
    except (RuntimeError, TimeoutError):
        # Google Maps often keeps background channels open after the useful DOM is ready.
        return


async def _open_reviews(tab: Any, sort_mode: SortMode) -> None:
    opened = await tab.eval_js(
        """(() => {
          const tab = Array.from(document.querySelectorAll('[role="tab"]'))
            .find(el => /Reviews/.test(el.getAttribute('aria-label') || el.innerText));
          if (!tab) return false;
          tab.click();
          return true;
        })()"""
    )
    if not opened:
        raise RuntimeError('Google Maps Reviews tab was not available')
    await _settle(tab)

    label = SORT_LABELS[sort_mode]
    menu_opened = await tab.eval_js(
        """(() => {
          const button = Array.from(document.querySelectorAll('button,[role="button"]'))
            .find(el => (el.getAttribute('aria-label') || el.innerText).trim() === 'Sort reviews');
          if (!button) return false;
          button.click();
          return true;
        })()"""
    )
    if not menu_opened:
        raise RuntimeError('Google Maps Sort reviews button was not available')

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=0.1, max=1),
        retry=retry_if_exception_type(_SortMenuNotReady),
        reraise=True,
    ):
        with attempt:
            sorted_ok = await tab.eval_js(
                f"""(() => {{
                  const option = Array.from(document.querySelectorAll('[role="menuitemradio"],[role="menuitem"]'))
                    .find(el => (el.getAttribute('aria-label') || el.innerText).trim() === {json.dumps(label)});
                  if (!option) return false;
                  option.click();
                  return true;
                }})()"""
            )
            if not sorted_ok:
                raise _SortMenuNotReady(f'Google Maps review sort option is not ready: {label}')
    await _settle(tab)


async def _review_count(tab: Any) -> int:
    value = await tab.eval_js(
        """(() => {
          const cards = Array.from(document.querySelectorAll('[data-review-id]'))
            .filter(el => el.innerText.trim().length >= 40);
          return new Set(cards.map(el => el.getAttribute('data-review-id')).filter(Boolean)).size;
        })()"""
    )
    return int(value)


async def _mark_scroll_container(tab: Any) -> None:
    marked = await tab.eval_js(
        """(() => {
          const card = Array.from(document.querySelectorAll('[data-review-id]'))
            .find(el => el.innerText.trim().length >= 40);
          let node = card;
          while (node) {
            if (node.scrollHeight > node.clientHeight + 100) {
              node.setAttribute('data-yosoi-review-scroll', '1');
              return true;
            }
            node = node.parentElement;
          }
          return false;
        })()"""
    )
    if not marked:
        raise RuntimeError('Google Maps review scroll container was not found')


async def _wait_for_review_growth(tab: Any, previous_count: int) -> int:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=0.1, max=1),
        retry=retry_if_exception_type(_ReviewsNotLoaded),
        reraise=True,
    ):
        with attempt:
            current = await _review_count(tab)
            if current <= previous_count:
                raise _ReviewsNotLoaded(f'review count remained at {current}')
            return current
    raise _ReviewsNotLoaded('review count did not increase')  # pragma: no cover


async def _load_reviews(tab: Any, limit: int) -> int:
    await _mark_scroll_container(tab)
    current = await _review_count(tab)
    max_scrolls = (limit // 5) + 5
    for _ in range(max_scrolls):
        if current >= limit:
            return current
        moved = await tab.eval_js(
            """(() => {
              const pane = document.querySelector('[data-yosoi-review-scroll="1"]');
              if (!pane) return false;
              pane.scrollTop = pane.scrollHeight;
              return true;
            })()"""
        )
        if not moved:
            break
        try:
            current = await _wait_for_review_growth(tab, current)
        except _ReviewsNotLoaded:
            break
    return current


async def _expand_review_cards(tab: Any, limit: int) -> None:
    clicked = await tab.eval_js(
        f"""(() => {{
          const best = new Map();
          for (const node of document.querySelectorAll('[data-review-id]')) {{
            const id = node.getAttribute('data-review-id');
            if (!id || node.innerText.trim().length < 40) continue;
            const score = (node.querySelector('[jsaction*=".review.share"]') ? 100 : 0)
              + (node.querySelector('[aria-label*=" stars"]') ? 10 : 0)
              + (node.querySelector('.d4r55') ? 5 : 0)
              + (Array.from(node.querySelectorAll('.wiI7pd')).some(el => !el.closest('.CDe7pd')) ? 1 : 0);
            const previous = best.get(id);
            if (!previous || score > previous.score) best.set(id, {{node, score}});
          }}
          const cards = Array.from(best.values()).map(value => value.node).slice(0, {limit});
          let count = 0;
          for (const card of cards) {{
            const more = Array.from(card.querySelectorAll('button,[role="button"]'))
              .find(el => (el.innerText || '').trim() === 'More' || (el.getAttribute('aria-label') || '') === 'See more');
            if (more) {{ more.click(); count += 1; }}
          }}
          return count;
        }})()"""
    )
    if not clicked:
        return

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=0.1, max=1),
        retry=retry_if_exception_type(_ReviewsNotExpanded),
        reraise=True,
    ):
        with attempt:
            remaining = await tab.eval_js(
                f"""(() => {{
                  const best = new Map();
                  for (const node of document.querySelectorAll('[data-review-id]')) {{
                    const id = node.getAttribute('data-review-id');
                    if (!id || node.innerText.trim().length < 40) continue;
                    const score = (node.querySelector('[jsaction*=".review.share"]') ? 100 : 0)
                      + (node.querySelector('[aria-label*=" stars"]') ? 10 : 0)
                      + (node.querySelector('.d4r55') ? 5 : 0);
                    const previous = best.get(id);
                    if (!previous || score > previous.score) best.set(id, {{node, score}});
                  }}
                  const cards = Array.from(best.values()).map(value => value.node).slice(0, {limit});
                  return cards.filter(card => Array.from(card.querySelectorAll('button,[role="button"]'))
                    .some(el => (el.innerText || '').trim() === 'More' || (el.getAttribute('aria-label') || '') === 'See more')).length;
                }})()"""
            )
            if remaining:
                raise _ReviewsNotExpanded(f'{remaining} review bodies remain truncated')


async def _extract_review_cards(tab: Any, limit: int) -> list[dict[str, Any]]:
    result = await tab.eval_js(
        f"""(() => {{
          const best = new Map();
          for (const node of document.querySelectorAll('[data-review-id]')) {{
            const id = node.getAttribute('data-review-id');
            if (!id || node.innerText.trim().length < 40) continue;
            const score = (node.querySelector('[jsaction*=".review.share"]') ? 100 : 0)
              + (node.querySelector('[aria-label*=" stars"]') ? 10 : 0)
              + (node.querySelector('.d4r55') ? 5 : 0)
              + (Array.from(node.querySelectorAll('.wiI7pd')).some(el => !el.closest('.CDe7pd')) ? 1 : 0);
            const previous = best.get(id);
            if (!previous || score > previous.score) best.set(id, {{node, score}});
          }}
          const cards = Array.from(best.values()).map(value => value.node).slice(0, {limit});

          return cards.map(card => {{
            const reviewText = Array.from(card.querySelectorAll('.wiI7pd'))
              .find(el => !el.closest('.CDe7pd'))?.innerText.trim() || null;
            const ownerResponse = card.querySelector('.CDe7pd .wiI7pd');
            const profile = card.querySelector('[data-href*="/maps/contrib/"]');
            const ratingLabel = Array.from(card.querySelectorAll('[aria-label]'))
              .map(el => (el.getAttribute('aria-label') || '').trim())
              .find(value => /^\\d(?:\\.\\d)? stars?$/i.test(value)) || '';
            return {{
              review_id: card.getAttribute('data-review-id'),
              reviewer_name: card.querySelector('.d4r55')?.innerText.trim() || card.getAttribute('aria-label') || '',
              reviewer_profile_url: profile?.getAttribute('data-href') || null,
              contribution_label: card.querySelector('.RfnDt')?.innerText.trim() || null,
              rating: Number.parseFloat(ratingLabel),
              relative_date: card.querySelector('.rsqaWe')?.innerText.trim() || '',
              review_text: reviewText,
              owner_response_text: ownerResponse?.innerText.trim() || null,
              owner_response_relative_date: card.querySelector('.DZSIDd')?.innerText.trim() || null
            }};
          }});
        }})()"""
    )
    return cast('list[dict[str, Any]]', result)


async def _wait_for_share_url(tab: Any) -> str:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=0.1, max=1),
        retry=retry_if_exception_type(_ShareDialogNotReady),
        reraise=True,
    ):
        with attempt:
            value = await tab.eval_js(
                """(() => {
                  const dialog = Array.from(document.querySelectorAll('[role="dialog"]'))
                    .find(el => /Review of/.test(el.innerText));
                  return dialog?.querySelector('input')?.value || null;
                })()"""
            )
            if not value:
                raise _ShareDialogNotReady('review share URL is not ready')
            return str(value)
    raise _ShareDialogNotReady('review share URL was unavailable')  # pragma: no cover


async def _review_share_url(tab: Any, review_id: str) -> str:
    share_mode = await tab.eval_js(
        f"""(() => {{
          const candidates = Array.from(document.querySelectorAll('[data-review-id]'))
            .filter(el => el.getAttribute('data-review-id') === {json.dumps(review_id)} && el.innerText.trim().length >= 40);
          const buttons = candidates.flatMap(card => Array.from(card.querySelectorAll('button,[role="button"]')));
          const share = buttons.find(el => (el.getAttribute('jsaction') || '').includes('.review.share'));
          if (share) {{ share.click(); return 'direct'; }}
          const menu = buttons.find(el => (el.getAttribute('jsaction') || '').includes('.review.actionMenu'));
          if (menu) {{ menu.click(); return 'menu'; }}
          return null;
        }})()"""
    )
    if share_mode == 'menu':
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(6),
            wait=wait_exponential(multiplier=0.1, max=1),
            retry=retry_if_exception_type(_ReviewMenuNotReady),
            reraise=True,
        ):
            with attempt:
                shared = await tab.eval_js(
                    """(() => {
                      const item = Array.from(document.querySelectorAll('[role="menuitem"],[role="menuitemradio"]'))
                        .find(el => (el.innerText || el.getAttribute('aria-label') || '').trim() === 'Share review');
                      if (!item) return false;
                      item.click();
                      return true;
                    })()"""
                )
                if not shared:
                    raise _ReviewMenuNotReady('Share review menu item is not ready')
    elif share_mode != 'direct':
        raise RuntimeError(f'Share action was unavailable for review {review_id}')

    url = await _wait_for_share_url(tab)
    closed = await tab.eval_js(
        """(() => {
          const dialog = Array.from(document.querySelectorAll('[role="dialog"]'))
            .find(el => /Review of/.test(el.innerText));
          const close = dialog && Array.from(dialog.querySelectorAll('button'))
            .find(el => (el.getAttribute('aria-label') || '') === 'Close');
          if (!close) return false;
          close.click();
          return true;
        })()"""
    )
    if not closed:
        raise RuntimeError(f'Share dialog did not close for review {review_id}')
    return url


def _to_review(raw: dict[str, Any], *, rank: int, sort_mode: SortMode, review_url: str) -> GoogleMapsReview:
    contribution = raw.get('contribution_label')
    profile_url = raw.get('reviewer_profile_url')
    return GoogleMapsReview(
        review_id=raw['review_id'],
        review_url=review_url,
        sample_rank=rank,
        sort_mode=sort_mode,
        rating=float(raw['rating']),
        review_text=raw.get('review_text'),
        relative_date=raw['relative_date'],
        reviewer_name=raw['reviewer_name'],
        reviewer_id=_reviewer_id(profile_url),
        reviewer_profile_url=profile_url,
        reviewer_reviews_count=_count_from_label(contribution, 'reviews?'),
        reviewer_photos_count=_count_from_label(contribution, 'photos?'),
        local_guide=bool(contribution and 'Local Guide' in contribution),
        owner_response_text=raw.get('owner_response_text'),
        owner_response_relative_date=raw.get('owner_response_relative_date'),
    )


async def scrape_reviews(
    *,
    business: str,
    location: str,
    limit: int,
    sort_mode: SortMode,
    fetcher_type: FetcherType,
) -> GoogleMapsReviewSample:
    """Acquire one bounded, sorted review sample."""
    business = business.strip()
    location = location.strip()
    if not business or not location:
        raise ValueError('business and location must not be empty')
    if not 1 <= limit <= MAX_REVIEWS:
        raise ValueError(f'limit must be between 1 and {MAX_REVIEWS}')
    if sort_mode not in SORT_LABELS:
        raise ValueError(f'unsupported review sort mode: {sort_mode}')
    if fetcher_type not in ('headless', 'headful'):
        raise ValueError(f'unsupported fetcher type: {fetcher_type}')
    source_url = build_maps_search_url(f'{business}, {location}')
    fetcher_cls = HeadlessFetcher if fetcher_type == 'headless' else HeadfulFetcher
    fetcher = fetcher_cls(timeout=45, max_concurrent=1, lightweight_fetch=True, console=Console(quiet=True))

    async with fetcher:
        for _ in range(2):
            warmup = await fetcher.fetch(source_url)
            if not warmup.success:
                raise RuntimeError(warmup.block_reason or 'Google Maps warm-up failed')
        async with fetcher.browse(source_url) as tab:
            await _settle(tab)
            await _open_reviews(tab, sort_mode)
            await _load_reviews(tab, limit)
            await _expand_review_cards(tab, limit)
            raw_reviews = await _extract_review_cards(tab, limit)
            reviews: list[GoogleMapsReview] = []
            for rank, raw in enumerate(raw_reviews, start=1):
                review_id = raw.get('review_id')
                if not isinstance(review_id, str) or not review_id:
                    raise ValueError(f'review at sample rank {rank} has no stable review ID')
                review_url = await _review_share_url(tab, review_id)
                reviews.append(_to_review(raw, rank=rank, sort_mode=sort_mode, review_url=review_url))

    return GoogleMapsReviewSample(
        business=business,
        location=location,
        source_url=source_url,
        sort_mode=sort_mode,
        requested_limit=limit,
        retrieved_count=len(reviews),
        captured_at=datetime.now(timezone.utc),
        reviews=reviews,
    )


def parse_args() -> argparse.Namespace:
    """Parse bounded review-sample options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business', default='Six Flags Over Georgia')
    parser.add_argument('--location', default='Austell, GA')
    parser.add_argument('--limit', type=_bounded_limit, default=MAX_REVIEWS, metavar='1-100')
    parser.add_argument('--sort', dest='sort_mode', choices=tuple(SORT_LABELS), default='newest')
    parser.add_argument('--fetcher', choices=('headless', 'headful'), default='headless')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


async def main() -> None:
    """Run the review workflow and write its validated JSON result."""
    args = parse_args()
    sample = await scrape_reviews(
        business=args.business,
        location=args.location,
        limit=args.limit,
        sort_mode=args.sort_mode,
        fetcher_type=args.fetcher,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sample.model_dump_json(indent=2), encoding='utf-8')
    print(
        f'{sample.business}: {sample.retrieved_count}/{sample.requested_limit} reviews '
        f'({sample.sort_mode}) -> {args.output}'
    )


if __name__ == '__main__':
    asyncio.run(main())
