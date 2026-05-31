"""Console output helpers for Yosoi runs.

Renders what Yosoi discovered for a domain — extracted records, the cached
selector snapshots, and the A3Node DOM-stability recipe — plus a ``banner``
heading primitive, so scripts and experiments can narrate a run without
hand-rolling print formatting.

Rendering only: these helpers never fetch or extract. ``report_selectors`` and
``report_a3node`` read already-persisted state from the storage layer; the rest
take data the caller already holds. Output goes through a Rich ``Console`` with
markup off and soft wrapping on, so long selector strings (including ``[...]``)
print literally and unbroken, matching plain ``print``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rich.console import Console

from yosoi.storage.a3node import A3NodeStorage
from yosoi.storage.persistence import SelectorStorage

__all__ = ['banner', 'print_records', 'report_a3node', 'report_selectors']

_RULE_WIDTH = 70
_console = Console()


def _resolve(console: Console | None) -> Console:
    return console or _console


def _line(console: Console, text: str) -> None:
    """Print one line literally — no markup parsing, no hard wrapping."""
    console.print(text, markup=False, soft_wrap=True)


def _rule(console: Console, char: str = '─') -> None:
    _line(console, char * _RULE_WIDTH)


def _heading(console: Console, title: str | None) -> None:
    """Print an optional section heading with a leading blank line."""
    if title:
        _line(console, f'\n  {title}')


def banner(title: str, *lines: str, console: Console | None = None) -> None:
    """Print a heavy-ruled banner with a title and optional subtitle lines.

    Args:
        title: Banner heading.
        lines: Extra lines printed under the title, inside the rules.
        console: Rich console to print to. Defaults to a shared module console.

    """
    con = _resolve(console)
    _rule(con, '═')
    _line(con, f'  {title}')
    for line in lines:
        _line(con, f'  {line}')
    _rule(con, '═')


def print_records(
    items: Sequence[Mapping[str, Any]],
    *,
    title: str = 'Extracted',
    console: Console | None = None,
) -> None:
    """Print extracted contract records, one non-empty field per line.

    Blank values are skipped so the output stays scannable.

    Args:
        items: Extracted records, each a ``field -> value`` mapping.
        title: Section heading shown above the records.
        console: Rich console to print to. Defaults to a shared module console.

    """
    con = _resolve(console)
    _rule(con)
    _line(con, f'  {title}')
    _rule(con)
    if not items:
        _line(con, '  (no items extracted)')
        return
    for item in items:
        for field, value in item.items():
            text = str(value or '').strip()
            if text:
                _line(con, f'  {field:<16} {text}')
    _rule(con)


async def report_selectors(
    storage: SelectorStorage,
    domain: str,
    *,
    title: str | None = None,
    console: Console | None = None,
) -> None:
    """Load and print the cached selector snapshots for *domain*.

    Args:
        storage: Selector storage to read from (e.g. ``pipeline.storage``).
        domain: Bare domain string (e.g. ``'google.com'``).
        title: Optional heading printed above the snapshots.
        console: Rich console to print to. Defaults to a shared module console.

    """
    con = _resolve(console)
    _heading(con, title)
    snapshots = await storage.load_snapshots(domain)
    if not snapshots:
        _line(con, '  No snapshots found.')
        return
    for field, snap in snapshots.items():
        primary = snap.primary or '—'
        fallback = snap.fallback or '—'
        status = snap.status.value
        source = snap.source or 'unknown'
        _line(con, f'  {field:<18} [{status:<8}] primary={primary!r}  fallback={fallback!r}  source={source}')


async def report_a3node(
    domain: str,
    *,
    title: str | None = None,
    storage: A3NodeStorage | None = None,
    console: Console | None = None,
) -> None:
    """Load and print the A3Node DOM-stability recipe for *domain*.

    Args:
        domain: Bare domain string.
        title: Optional heading printed above the recipe.
        storage: A3Node storage to read from. Defaults to a fresh ``A3NodeStorage()``.
        console: Rich console to print to. Defaults to a shared module console.

    """
    con = _resolve(console)
    _heading(con, title)
    node = await (storage or A3NodeStorage()).load(domain)
    if node is None:
        _line(con, '  No A3Node recorded.')
        return
    if node.is_empty:
        _line(con, f'  A3Node: empty recipe (no DOM actions needed)  replays={node.replay_count}')
        return
    _line(con, f'  A3Node: {len(node.acts)} act(s)  replays={node.replay_count}')
    for act in node.acts:
        _line(con, f'    • {act.kind}  cycles={act.cycles}')
