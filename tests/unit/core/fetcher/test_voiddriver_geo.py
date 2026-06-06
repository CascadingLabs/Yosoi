"""Teleport-at-fetch: BrowserIdentity.geo is applied to the tab before navigation."""

from __future__ import annotations

from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.core.fetcher.voiddriver import HeadlessFetcher


class _GeoTab:
    def __init__(self) -> None:
        self.geo: tuple[float, float] | None = None

    async def set_geolocation(self, lat: float, lon: float) -> None:
        self.geo = (lat, lon)


async def test_apply_identity_geo_spoofs_location() -> None:
    fetcher = HeadlessFetcher(identity=BrowserIdentity(id='loc', geo=(38.2527, -85.7585)))
    tab = _GeoTab()
    await fetcher._apply_identity_geo(tab)
    assert tab.geo == (38.2527, -85.7585)


async def test_apply_identity_geo_noop_without_geo() -> None:
    fetcher = HeadlessFetcher(identity=BrowserIdentity(id='loc'))  # no geo
    tab = _GeoTab()
    await fetcher._apply_identity_geo(tab)
    assert tab.geo is None


async def test_apply_identity_geo_noop_without_identity() -> None:
    fetcher = HeadlessFetcher()  # no identity
    tab = _GeoTab()
    await fetcher._apply_identity_geo(tab)
    assert tab.geo is None


async def test_apply_identity_geo_tolerates_tab_without_setter() -> None:
    fetcher = HeadlessFetcher(identity=BrowserIdentity(id='loc', geo=(1.0, 2.0)))
    await fetcher._apply_identity_geo(object())  # no set_geolocation — must not raise
