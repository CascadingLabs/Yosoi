# yosoi: allow-hardcoded-selectors -- site-specific validators contain regexes, not extraction selectors.
"""Dogfood an exact-business Google Maps query with a small Yosoi contract.

Print the canonical URL and Jinja2 inputs without scraping:
    uv run python examples/google_maps/google_maps.py --url-only

Warm an anonymous VoidCrawl browser pool, then run selector discovery and extraction:
    uv run python examples/google_maps/google_maps.py

Compare the cold one-shot public operation:
    uv run python examples/google_maps/google_maps.py --cold
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from functools import lru_cache
from typing import ClassVar
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import model_serializer
from rich.console import Console

import yosoi as ys
from yosoi.core.fetcher.voiddriver import HeadfulFetcher, HeadlessFetcher

MAPS_SEARCH_BASE = 'https://www.google.com/maps/search/'
MAPS_SEARCH_TEMPLATE = (
    'https://www.google.com/maps/search/?api=1'
    '&query={{ query | urlencode }}'
    '{% if query_place_id %}&query_place_id={{ query_place_id | urlencode }}{% endif %}'
)
_PLUS_CODE_RE = re.compile(
    r'(?:[23456789CFGHJMPQRVWX]{2}){1,4}\+[23456789CFGHJMPQRVWX]{2,3}(?:\s+.+)?',
    re.IGNORECASE,
)
_WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
_TIME_TOKEN = r'(?:\d{1,2}(?::\d{1,2})?\s*(?:am|pm)?|noon|midnight)'
_TIME_RANGE_RE = re.compile(
    rf'^(?P<opens>{_TIME_TOKEN})\s*(?:-|–|—|‑|−|to)\s*(?P<closes>{_TIME_TOKEN})$',
    re.IGNORECASE,
)
_TIME_RE = re.compile(r'^(?P<hour>\d{1,2})(?::(?P<minute>\d{1,2}))?\s*(?P<meridiem>am|pm)?$', re.IGNORECASE)


@lru_cache(maxsize=1)
def _iana_timezones() -> frozenset[str]:
    """Cache the installed IANA key set used to exclude ZoneInfo's special files."""
    return frozenset(available_timezones())


def _explicit_meridiem(value: str) -> str | None:
    """Return an explicitly stated meridiem, including the noon/midnight aliases."""
    normalized = value.strip().replace('.', '').casefold()
    if normalized == 'midnight':
        return 'AM'
    if normalized == 'noon':
        return 'PM'
    match = _TIME_RE.fullmatch(normalized)
    return match.group('meridiem').upper() if match is not None and match.group('meridiem') else None


def _minutes_since_midnight(value: str, meridiem: str) -> int:
    """Return one numeric wall-clock token as minutes for meridiem inference."""
    normalized = value.strip().replace('.', '').casefold()
    if normalized == 'midnight':
        return 0
    if normalized == 'noon':
        return 12 * 60
    match = _TIME_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(f'invalid time {value!r}')
    hour = int(match.group('hour'))
    minute = int(match.group('minute') or 0)
    if not 1 <= hour <= 12 or minute > 59:
        raise ValueError(f'invalid 12-hour time {value!r}')
    return (hour % 12) * 60 + minute + (12 * 60 if meridiem == 'PM' else 0)


def _infer_meridiem(value: str, counterpart: str, *, value_is_opening: bool) -> str:
    """Choose the AM/PM candidate yielding the shortest positive range."""
    counterpart_meridiem = _explicit_meridiem(counterpart)
    if counterpart_meridiem is None:  # pragma: no cover - guarded by the caller
        raise ValueError('cannot infer meridiem without an explicit counterpart')
    counterpart_minutes = _minutes_since_midnight(counterpart, counterpart_meridiem)

    def duration(candidate: str) -> int:
        candidate_minutes = _minutes_since_midnight(value, candidate)
        opens, closes = (
            (candidate_minutes, counterpart_minutes) if value_is_opening else (counterpart_minutes, candidate_minutes)
        )
        elapsed = (closes - opens) % (24 * 60)
        return elapsed or 24 * 60

    return min(('AM', 'PM'), key=duration)


def _canonical_time(value: str, *, default_meridiem: str | None = None) -> str:
    """Parse one 12- or 24-hour wall-clock value into the example's display grammar."""
    normalized = value.strip().replace('.', '').casefold()
    if normalized == 'midnight':
        return '12 AM'
    if normalized == 'noon':
        return '12 PM'

    match = _TIME_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(f'invalid time {value!r}')

    hour = int(match.group('hour'))
    minute_text = match.group('minute')
    minute = int(minute_text or 0)
    meridiem = match.group('meridiem') or default_meridiem
    if minute > 59:
        raise ValueError(f'invalid minute in {value!r}')

    if meridiem is not None:
        if not 1 <= hour <= 12:
            raise ValueError(f'invalid 12-hour time {value!r}')
        canonical_hour = hour
        canonical_meridiem = meridiem.upper()
    else:
        if minute_text is None:
            raise ValueError(f'missing AM/PM in {value!r}')
        if not 0 <= hour <= 23:
            raise ValueError(f'invalid 24-hour time {value!r}')
        canonical_hour = 12 if hour % 12 == 0 else hour % 12
        canonical_meridiem = 'AM' if hour < 12 else 'PM'

    canonical_minute = '' if minute == 0 else f':{minute:02d}'
    return f'{canonical_hour}{canonical_minute} {canonical_meridiem}'


def _canonical_period(period: str) -> str:
    """Normalize one opening-hours range after outer list punctuation is removed."""
    match = _TIME_RANGE_RE.fullmatch(period)
    if match is None:
        raise ValueError(f'unrecognized opening-hours period {period!r}')
    opens_value = match.group('opens')
    closes_value = match.group('closes')
    opens_meridiem = _explicit_meridiem(opens_value)
    closes_meridiem = _explicit_meridiem(closes_value)
    if opens_meridiem is None and closes_meridiem is not None:
        opens_meridiem = _infer_meridiem(opens_value, closes_value, value_is_opening=True)
    if closes_meridiem is None and opens_meridiem is not None:
        closes_meridiem = _infer_meridiem(closes_value, opens_value, value_is_opening=False)
    opens = _canonical_time(opens_value, default_meridiem=opens_meridiem)
    closes = _canonical_time(closes_value, default_meridiem=closes_meridiem)
    if opens == closes:
        raise ValueError('equal opening and closing times are ambiguous; use Closed or Open 24 hours')
    return f'{opens}–{closes}'


def normalize_opening_hours(value: object, *, weekday: str | None = None) -> str | None:
    """Normalize one Google Maps weekday value without changing its local-time semantics."""
    if value is None:
        return None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        value = ', '.join(value)
    if not isinstance(value, str):
        raise ValueError('opening hours must be text')

    normalized = re.sub(r'[\n;]+', ', ', value)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    if weekday is not None:
        normalized = re.sub(rf'^{re.escape(weekday)}\s*[:,]\s*', '', normalized, flags=re.IGNORECASE)
    sentinel = normalized.replace('.', '').casefold()
    if sentinel == 'closed':
        return 'Closed'
    if sentinel in {'24 hours', '24 hrs', 'open 24 hours', 'open 24 hrs', 'open 24hrs'}:
        return 'Open 24 hours'

    periods = [period.strip() for period in normalized.replace('.', '').split(',')]
    if not periods or any(not period for period in periods):
        raise ValueError('opening hours contain an empty period')

    return ', '.join(_canonical_period(period) for period in periods)


class _ScheduleValidators:
    """Portable field transforms retained when a Schedule spec is rehydrated."""

    @staticmethod
    def timezone(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError('timezone must be an explicit IANA identifier') from error
        if value not in _iana_timezones():
            raise ValueError('timezone must be an explicit IANA identifier')
        return value

    @staticmethod
    def monday(value: object) -> str | None:
        return normalize_opening_hours(value, weekday='monday')

    @staticmethod
    def tuesday(value: object) -> str | None:
        return normalize_opening_hours(value, weekday='tuesday')

    @staticmethod
    def wednesday(value: object) -> str | None:
        return normalize_opening_hours(value, weekday='wednesday')

    @staticmethod
    def thursday(value: object) -> str | None:
        return normalize_opening_hours(value, weekday='thursday')

    @staticmethod
    def friday(value: object) -> str | None:
        return normalize_opening_hours(value, weekday='friday')

    @staticmethod
    def saturday(value: object) -> str | None:
        return normalize_opening_hours(value, weekday='saturday')

    @staticmethod
    def sunday(value: object) -> str | None:
        return normalize_opening_hours(value, weekday='sunday')


class Schedule(ys.Contract):
    """Normalized regular weekly hours in the place's local timezone."""

    Validators: ClassVar[type[_ScheduleValidators]] = _ScheduleValidators

    timezone: str | None = ys.Field(
        default=None,
        description='IANA timezone exactly as explicitly published by the source; never infer it from location or offset',
    )
    monday: str | None = ys.Field(default=None, description='Monday regular hours from the primary business panel')
    tuesday: str | None = ys.Field(default=None, description='Tuesday regular hours from the primary business panel')
    wednesday: str | None = ys.Field(
        default=None, description='Wednesday regular hours from the primary business panel'
    )
    thursday: str | None = ys.Field(default=None, description='Thursday regular hours from the primary business panel')
    friday: str | None = ys.Field(default=None, description='Friday regular hours from the primary business panel')
    saturday: str | None = ys.Field(default=None, description='Saturday regular hours from the primary business panel')
    sunday: str | None = ys.Field(default=None, description='Sunday regular hours from the primary business panel')

    @property
    def days(self) -> dict[str, str | None]:
        """Return a stable seven-day mapping; null means unavailable, never closed."""
        return {day: getattr(self, day) for day in _WEEKDAYS}

    @model_serializer(mode='plain')
    def serialize_schedule(self) -> dict[str, object]:
        """Keep selector-friendly fields internal while presenting a day mapping."""
        return {'timezone': self.timezone, 'days': self.days}


class _GoogleMapsPlaceValidators:
    """Portable place validators retained when the contract spec is rehydrated."""

    @staticmethod
    def plus_code(value: str) -> str:
        normalized = value.strip()
        if not _PLUS_CODE_RE.fullmatch(normalized):
            raise ValueError('value is not a Google Maps Plus Code')
        return normalized


class GoogleMapsPlace(ys.Contract):
    """The exact business shown in the primary Google Maps detail panel."""

    Validators: ClassVar[type[_GoogleMapsPlaceValidators]] = _GoogleMapsPlaceValidators

    name: str = ys.Title(description='Name in the primary business detail panel')
    rating: float = ys.Rating(
        as_float=True,
        description='Star rating for the primary business, excluding nearby places',
    )
    review_count: int = ys.Field(
        description='Total review count adjacent to the primary business star rating, excluding nearby places'
    )
    address: str = ys.Field(description='Listed street address in the primary business detail panel')
    phone: str | None = ys.Field(
        default=None,
        description='Phone number in the primary business detail panel, or none when not published',
    )
    website: str | None = ys.Url(
        default=None,
        strip_tracking=True,
        description='Destination URL of the listed business website, excluding Google Maps links',
    )
    plus_code: str = ys.Field(description='Google Maps Plus Code and locality from the primary business detail panel')
    schedule: Schedule = ys.Field(
        default_factory=Schedule,
        description='Regular weekly hours from the primary business panel; excludes special and secondary hours',
    )


def build_maps_search_url(query: str, *, query_place_id: str | None = None) -> str:
    """Build an official Google Maps search URL from stable public parameters."""
    query = query.strip()
    if not query:
        raise ValueError('Google Maps search query must not be empty')
    params = {'api': '1', 'query': query}
    if query_place_id and (query_place_id := query_place_id.strip()):
        params['query_place_id'] = query_place_id
    return f'{MAPS_SEARCH_BASE}?{urlencode(params)}'


def parse_args() -> argparse.Namespace:
    """Parse example inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business', default='Six Flags Over Georgia')
    parser.add_argument('--location', default='Austell, GA')
    parser.add_argument('--place-id', help='Optional Google Place ID for identity-level exactness')
    parser.add_argument('--fetcher', choices=('headless', 'headful'), default='headless')
    parser.add_argument('--cold', action='store_true', help='Skip the anonymous warm-up and use one-shot ys.scrape')
    parser.add_argument('--url-only', action='store_true', help='Print URL/template information without scraping')
    return parser.parse_args()


async def scrape_warm(url: str, *, fetcher_type: str, policy: ys.Policy) -> list[dict[str, object]]:
    """Warm one anonymous browser pool, then scrape through that same pool."""
    fetcher_cls = HeadlessFetcher if fetcher_type == 'headless' else HeadfulFetcher
    fetcher = fetcher_cls(
        timeout=45,
        max_concurrent=1,
        lightweight_fetch=True,
        console=Console(quiet=True),
    )
    async with fetcher:
        warmup = await fetcher.fetch(url)
        if not warmup.success:
            raise RuntimeError(warmup.block_reason or 'Google Maps warm-up failed')
        async with ys.Pipeline(contract=GoogleMapsPlace, policy=policy, quiet=False) as pipeline:
            return [
                item
                async for item in pipeline.scrape(
                    url,
                    fetcher_type=fetcher_type,
                    fetcher=fetcher,
                )
            ]


async def main() -> None:
    """Build the exact-business URL and optionally scrape its detail panel."""
    args = parse_args()
    query = ', '.join(part for part in (args.business.strip(), args.location.strip()) if part)
    place_id = args.place_id.strip() if args.place_id and args.place_id.strip() else None
    context = {'query': query, 'query_place_id': place_id}
    url = build_maps_search_url(query, query_place_id=place_id)

    print(f'Jinja2 template:\n{MAPS_SEARCH_TEMPLATE}')
    print(f'Jinja2 context:\n{json.dumps(context, indent=2)}')
    print(f'Rendered URL:\n{url}')

    if args.url_only:
        return

    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(fetcher_type=args.fetcher),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    display_result: object
    if args.cold:
        display_result = await ys.scrape(url, GoogleMapsPlace, policy=policy)
    else:
        display_result = await scrape_warm(url, fetcher_type=args.fetcher, policy=policy)
    ys.show(display_result)


if __name__ == '__main__':
    asyncio.run(main())
