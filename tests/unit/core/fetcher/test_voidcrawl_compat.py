"""Compatibility checks for the VoidCrawl browser API Yosoi calls."""

from __future__ import annotations

from typing import Any


def test_voidcrawl_032_exposes_accessibility_tree_methods() -> None:
    import voidcrawl

    expected_methods = (
        'get_full_ax_tree',
        'ax_tree_outline',
        'query_ax_tree',
        'click_by_role',
    )

    for cls in (voidcrawl.Page, voidcrawl.PooledTab):
        missing = [name for name in expected_methods if not hasattr(cls, name)]
        assert missing == []


def test_voidcrawl_032_browser_config_accepts_chrome_executable() -> None:
    from voidcrawl import BrowserConfig

    config: Any = BrowserConfig(chrome_executable='/opt/chrome', headless=True)

    assert config.chrome_executable == '/opt/chrome'
    assert config.headless is True
