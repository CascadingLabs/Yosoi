"""Discovery-time geocoding for teleport plans (geopy / Nominatim).

DISCOVERY-TIME ONLY. ``geopy`` (and its ``geographiclib`` transitive) is imported
*inside* the helper bodies, never at module top level, so that importing this module
— or anything on the replay hot path — does not drag geopy in. The persisted
:class:`~yosoi.models.replay.TeleportSpec` carries LITERAL coordinates, so replay
never needs geopy at all (CAS-87 import-light invariant). A regression test asserts
``import yosoi.core.replay.runtime`` does not transitively import geopy.

Mirrors ``nimbal/core/geocode.py``: ``"{city}, {state}"`` disambiguates same-name
cities (Arlington TX vs VA → distinct coords), results are cached on disk because
Nominatim is rate-limited (1 req/s) and coordinates are stable, and descriptive
franchise territories ("Greater Charlotte Area") are marketing-stripped before a
fallback geocode — returning ``None`` when unresolvable so the caller routes to a
``words``-localization plan (city/state baked into the query) instead of teleporting
to a wrong/center-of-country coordinate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from yosoi.models.replay import TeleportSpec

if TYPE_CHECKING:
    from geopy.geocoders import Nominatim

# Nominatim TOS: 1 req/s and a real, contactful User-Agent. Mirror Nimbal's value.
_USER_AGENT = 'yosoi-discovery/0.1 (andberg9@gmail.com)'
_MIN_DELAY_SECONDS = 1.1

# Strip franchise-territory marketing language so a real place name remains.
_STRIP = re.compile(
    r'\b(greater|the|area|region|metro(?:politan)?|north|south|east|west|central|county|coast|valley)\b',
    re.I,
)

# Module-level on-disk cache state. Lazily initialised so importing this module is
# cheap and side-effect free; the geocoder itself is built only on a cache miss.
_DEFAULT_CACHE = Path('.yosoi') / 'geocode_cache.json'


def _load_cache(path: Path) -> dict[str, list[float] | None]:
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
        if isinstance(loaded, dict):
            return loaded
    return {}


def _save_cache(path: Path, cache: dict[str, list[float] | None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=0))


def _build_geocoder() -> Nominatim:
    """Construct the rate-limited Nominatim geocoder — lazy geopy import lives here.

    Imported inside the function body so neither this module's import nor the replay
    hot path ever pulls geopy/geographiclib.
    """
    from geopy.geocoders import Nominatim

    return Nominatim(user_agent=_USER_AGENT)


def geocode(
    city: str,
    state: str | None = None,
    *,
    country_codes: str = 'us',
    cache_path: Path | None = None,
) -> tuple[float, float] | None:
    """Return cached ``(lat, lon)`` for a real ``city`` (+ ``state``), or ``None``.

    Lazy-imports geopy only on a cache miss. ``country_codes`` constrains Nominatim;
    ``cache_path`` overrides the on-disk cache (tests point it at a tmp file).
    """
    path = cache_path or _DEFAULT_CACHE
    q = f'{city}, {state}'.strip().strip(',') if state else city.strip()
    if not q:
        return None
    cache = _load_cache(path)
    if q in cache:
        v = cache[q]
        return (v[0], v[1]) if v else None
    from geopy.extra.rate_limiter import RateLimiter

    lookup = RateLimiter(
        _build_geocoder().geocode,
        min_delay_seconds=_MIN_DELAY_SECONDS,
        swallow_exceptions=True,
    )
    loc = lookup(q, country_codes=country_codes, timeout=10)
    coords: list[float] | None = [loc.latitude, loc.longitude] if loc else None
    cache[q] = coords
    _save_cache(path, cache)
    return (coords[0], coords[1]) if coords else None


def geocode_territory(
    territory: str,
    state: str | None = None,
    *,
    cache_path: Path | None = None,
) -> tuple[float, float] | None:
    """Geocode a (possibly descriptive) franchise territory.

    Tries it verbatim, then a marketing-stripped core, then ``None`` (caller falls
    back to a words-in-query plan).
    """
    direct = geocode(territory, state, cache_path=cache_path)
    if direct:
        return direct
    core = ' '.join(w for w in _STRIP.sub(' ', territory).split() if w).strip(', ')
    if core and core.lower() != territory.lower():
        return geocode(core, state, cache_path=cache_path)
    return None


def teleport_spec_for(
    city: str,
    state: str | None = None,
    *,
    timezone: str | None = None,
    locale: str | None = None,
    territory: bool = False,
    cache_path: Path | None = None,
) -> TeleportSpec | None:
    """Build a :class:`TeleportSpec` for ``city``/``state`` at discovery time.

    Returns ``None`` when the location does not geocode — the signal for the caller
    to emit a ``words``-localization plan (no ``TeleportSpec``; city/state baked into
    the query string) rather than teleporting to a wrong coordinate. ``territory=True``
    routes through :func:`geocode_territory` (marketing-prefix stripping) for franchise
    territory names. The resulting spec carries LITERAL coords, so the persisted plan
    needs no geopy at replay time.
    """
    coords = (
        geocode_territory(city, state, cache_path=cache_path)
        if territory
        else geocode(city, state, cache_path=cache_path)
    )
    if coords is None:
        return None
    lat, lon = coords
    return TeleportSpec(latitude=lat, longitude=lon, timezone=timezone, locale=locale)
