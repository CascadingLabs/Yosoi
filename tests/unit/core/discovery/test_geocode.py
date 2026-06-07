"""W3: discovery-time geopy helper — mocked geocoder, NO network.

Covers city/state geocoding, on-disk cache hit/miss, territory marketing-strip
fallback, None→words-plan routing, and TeleportSpec assembly. The geopy network
call is mocked at the ``_build_geocoder`` chokepoint so no test ever hits Nominatim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yosoi.core.discovery import geocode as geo
from yosoi.models.replay import TeleportSpec


class _FakeLoc:
    def __init__(self, lat: float, lon: float) -> None:
        self.latitude = lat
        self.longitude = lon


class _FakeGeocoder:
    """Stands in for geopy.Nominatim; records queries, returns canned coords."""

    def __init__(self, table: dict[str, tuple[float, float]]) -> None:
        self._table = table
        self.queries: list[str] = []

    def geocode(self, query, **kwargs):
        self.queries.append(query)
        hit = self._table.get(query)
        return _FakeLoc(*hit) if hit else None


@pytest.fixture
def patched_geocoder(monkeypatch):
    """Patch _build_geocoder so no real geopy/Nominatim/network is touched.

    Returns the fake so a test can inspect which queries were issued.
    """
    fake = _FakeGeocoder(
        {
            'Arlington, VA': (38.8799, -77.1068),
            'Arlington, TX': (32.7357, -97.1081),
            'Charlotte, NC': (35.2271, -80.8431),
        }
    )
    monkeypatch.setattr(geo, '_build_geocoder', lambda: fake)
    # Defang the RateLimiter delay so tests don't sleep 1.1s.
    import geopy.extra.rate_limiter as rl

    def _no_sleep(_self: object) -> None:
        return None

    monkeypatch.setattr(rl.RateLimiter, '_sleep_between_queries', _no_sleep, raising=False)
    return fake


def test_geocode_city_state_distinct_coords(patched_geocoder, tmp_path):
    cache = tmp_path / 'gc.json'
    va = geo.geocode('Arlington', 'VA', cache_path=cache)
    tx = geo.geocode('Arlington', 'TX', cache_path=cache)
    assert va == (38.8799, -77.1068)
    assert tx == (32.7357, -97.1081)
    assert va != tx


def test_geocode_caches_to_disk_and_skips_second_lookup(patched_geocoder, tmp_path):
    cache = tmp_path / 'gc.json'
    geo.geocode('Charlotte', 'NC', cache_path=cache)
    assert patched_geocoder.queries == ['Charlotte, NC']
    # Cache file written.
    data = json.loads(cache.read_text())
    assert data['Charlotte, NC'] == [35.2271, -80.8431]
    # Second call is a cache hit → no new geocoder query.
    again = geo.geocode('Charlotte', 'NC', cache_path=cache)
    assert again == (35.2271, -80.8431)
    assert patched_geocoder.queries == ['Charlotte, NC']


def test_geocode_unresolved_caches_none(patched_geocoder, tmp_path):
    cache = tmp_path / 'gc.json'
    assert geo.geocode('Nowheresville', 'ZZ', cache_path=cache) is None
    data = json.loads(cache.read_text())
    assert data['Nowheresville, ZZ'] is None


def test_geocode_empty_query_returns_none(patched_geocoder, tmp_path):
    assert geo.geocode('', None, cache_path=tmp_path / 'gc.json') is None
    assert patched_geocoder.queries == []


def test_geocode_territory_strips_marketing_prefix(patched_geocoder, tmp_path):
    cache = tmp_path / 'gc.json'
    # "Greater Charlotte Area" doesn't resolve verbatim, but stripped core "Charlotte" does.
    coords = geo.geocode_territory('Greater Charlotte Area', 'NC', cache_path=cache)
    assert coords == (35.2271, -80.8431)
    # Both the verbatim and the stripped-core queries were attempted.
    assert 'Greater Charlotte Area, NC' in patched_geocoder.queries
    assert 'Charlotte, NC' in patched_geocoder.queries


def test_geocode_territory_unresolvable_returns_none(patched_geocoder, tmp_path):
    coords = geo.geocode_territory('Greater Nowhere Region', 'ZZ', cache_path=tmp_path / 'gc.json')
    assert coords is None


def test_teleport_spec_for_builds_literal_spec(patched_geocoder, tmp_path):
    spec = geo.teleport_spec_for(
        'Arlington',
        'VA',
        timezone='America/New_York',
        locale='en-US',
        cache_path=tmp_path / 'gc.json',
    )
    assert isinstance(spec, TeleportSpec)
    assert spec.latitude == 38.8799
    assert spec.longitude == -77.1068
    assert spec.timezone == 'America/New_York'
    assert spec.locale == 'en-US'


def test_teleport_spec_for_unresolved_routes_to_words_plan(patched_geocoder, tmp_path):
    """None means: caller emits a words-localization plan, not a teleport plan."""
    spec = geo.teleport_spec_for('Nowheresville', 'ZZ', cache_path=tmp_path / 'gc.json')
    assert spec is None


def test_teleport_spec_for_territory_routes_through_strip(patched_geocoder, tmp_path):
    spec = geo.teleport_spec_for(
        'Greater Charlotte Area',
        'NC',
        territory=True,
        cache_path=tmp_path / 'gc.json',
    )
    assert spec is not None
    assert spec.latitude == 35.2271


def test_geocode_corrupt_cache_recovers(patched_geocoder, tmp_path):
    cache: Path = tmp_path / 'gc.json'
    cache.write_text('{not valid json')
    # Should not raise; falls back to empty cache and geocodes fresh.
    assert geo.geocode('Charlotte', 'NC', cache_path=cache) == (35.2271, -80.8431)
