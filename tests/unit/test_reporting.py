"""Tests for the console reporting helpers."""

import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from rich.console import Console

from yosoi.models.snapshot import SelectorSnapshot, SnapshotStatus
from yosoi.reporting import banner, print_records, report_a3node, report_selectors
from yosoi.storage.a3node import A3NodeStorage, ActRecord
from yosoi.storage.persistence import SelectorStorage

pytestmark = pytest.mark.unit


def _capture() -> tuple[Console, io.StringIO]:
    """Return a Rich console that writes to an in-memory buffer."""
    buf = io.StringIO()
    return Console(file=buf, width=200, force_terminal=False), buf


def test_print_records_renders_non_empty_fields() -> None:
    console, buf = _capture()
    print_records(
        [{'name': 'Acme', 'rating': '4.8', 'phone': ''}],
        title='Extracted (Phase 1)',
        console=console,
    )
    out = buf.getvalue()
    assert 'Extracted (Phase 1)' in out
    assert 'Acme' in out
    assert '4.8' in out
    # Blank values are skipped.
    assert 'phone' not in out


def test_print_records_empty() -> None:
    console, buf = _capture()
    print_records([], console=console)
    assert '(no items extracted)' in buf.getvalue()


async def test_report_selectors_renders_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YOSOI_HOME', str(tmp_path))
    storage = SelectorStorage()
    # A selector containing brackets must print literally (markup disabled).
    bracketed = 'meta[name="yosoi-review-count"]::attr(content)'
    await storage.save_snapshots(
        'https://example.com/page',
        {
            'review_count': SelectorSnapshot(
                primary=bracketed,
                discovered_at=datetime.now(timezone.utc),
                source='pinned',
                status=SnapshotStatus.ACTIVE,
            )
        },
    )

    console, buf = _capture()
    await report_selectors(storage, 'example.com', console=console)
    out = buf.getvalue()
    assert 'review_count' in out
    assert bracketed in out
    assert 'active' in out
    assert 'pinned' in out


async def test_report_selectors_no_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YOSOI_HOME', str(tmp_path))
    console, buf = _capture()
    await report_selectors(SelectorStorage(), 'never-seen.com', console=console)
    assert 'No snapshots found.' in buf.getvalue()


async def test_report_a3node_with_acts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YOSOI_HOME', str(tmp_path))
    storage = A3NodeStorage()
    await storage.save('example.com', [ActRecord('cookie', 1), ActRecord('load_more', 7)])

    console, buf = _capture()
    # Passes storage explicitly; default-storage path is exercised below.
    await report_a3node('example.com', storage=storage, console=console)
    out = buf.getvalue()
    assert 'A3Node: 2 act(s)' in out
    assert 'load_more' in out
    assert 'cycles=7' in out


async def test_report_a3node_empty_recipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YOSOI_HOME', str(tmp_path))
    storage = A3NodeStorage()
    await storage.save('example.com', [])

    console, buf = _capture()
    # No explicit storage -> exercises the default A3NodeStorage() branch.
    await report_a3node('example.com', console=console)
    assert 'empty recipe' in buf.getvalue()


async def test_report_a3node_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YOSOI_HOME', str(tmp_path))
    console, buf = _capture()
    await report_a3node('never-seen.com', storage=A3NodeStorage(), console=console)
    assert 'No A3Node recorded.' in buf.getvalue()


def test_banner_with_and_without_subtitle_lines() -> None:
    console, buf = _capture()
    banner('PHASE 1 — single URL seed', 'discovering selectors', console=console)
    banner('PHASE 2', console=console)  # zero subtitle lines
    out = buf.getvalue()
    assert 'PHASE 1 — single URL seed' in out
    assert 'discovering selectors' in out
    assert 'PHASE 2' in out
    assert '═' in out


async def test_report_selectors_title_heading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YOSOI_HOME', str(tmp_path))
    console, buf = _capture()
    await report_selectors(SelectorStorage(), 'never-seen.com', title='Cached selectors', console=console)
    out = buf.getvalue()
    assert 'Cached selectors' in out
    assert 'No snapshots found.' in out


async def test_report_a3node_title_heading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YOSOI_HOME', str(tmp_path))
    console, buf = _capture()
    await report_a3node('never-seen.com', title='A3Node recipe', storage=A3NodeStorage(), console=console)
    out = buf.getvalue()
    assert 'A3Node recipe' in out
    assert 'No A3Node recorded.' in out
