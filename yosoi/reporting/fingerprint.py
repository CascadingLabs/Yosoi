"""Rich reporting helpers for page fingerprints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rich.table import Table

from yosoi.generalization.fingerprint import PageFingerprint


def fingerprint_table(value: object, compare_to: object | None = None) -> Table:
    """Build a terminal table for one fingerprint or a two-page comparison."""
    left = coerce_fingerprint(value)
    if compare_to is None:
        return _summary_table(left)

    right = coerce_fingerprint(compare_to)
    return _comparison_table(left, right)


def coerce_fingerprint(
    source: object,
    *,
    ax_snapshot: Any = None,
    headers: Mapping[str, str] | None = None,
    endpoints: Sequence[str] | None = None,
) -> PageFingerprint:
    """Coerce HTML, a fetch result, or a PageFingerprint into a PageFingerprint."""
    if isinstance(source, PageFingerprint):
        return source

    html = source if isinstance(source, str) else getattr(source, 'html', None)
    if not isinstance(html, str) or not html:
        raise ValueError('fingerprint reporting needs an HTML string, PageFingerprint, or object with non-empty .html')

    if not isinstance(source, str):
        if ax_snapshot is None:
            ax_snapshot = getattr(source, 'ax_snapshot', None)
        if headers is None:
            headers = getattr(source, 'headers', None)
        if endpoints is None:
            endpoints = getattr(source, 'endpoints', None)

    return PageFingerprint.of(html, ax_snapshot=ax_snapshot, headers=headers, endpoints=endpoints)


def _summary_table(fp: PageFingerprint) -> Table:
    table = Table(title='Fingerprint', show_lines=False)
    table.add_column('layer')
    table.add_column('features', justify='right')
    table.add_column('carried')

    rows = [
        ('skeleton', fp.skeleton, True),
        ('semantic', fp.semantic, True),
        ('identity', fp.identity, bool(fp.identity)),
        ('ax', fp.ax_spine, bool(fp.ax_spine)),
        ('network', fp.network, bool(fp.network)),
        ('endpoint', fp.endpoints, bool(fp.endpoints)),
    ]
    for name, features, carried in rows:
        table.add_row(name, str(len(features)), 'yes' if carried else 'no')

    table.add_row('degenerate', 'yes' if fp.degenerate else 'no', 'n/a')
    return table


def _comparison_table(left: PageFingerprint, right: PageFingerprint) -> Table:
    similarity = left.similarity(right)
    table = Table(title='Fingerprint comparison', show_lines=False)
    table.add_column('layer')
    table.add_column('similarity', justify='right')
    table.add_column('verdict')

    rows = [
        ('same_shape', None, 'yes' if similarity.same_shape else 'no'),
        ('skeleton', similarity.skeleton, ''),
        ('semantic', similarity.semantic, ''),
        ('identity', similarity.identity, _optional_verdict(similarity.identity)),
        ('ax', similarity.ax, _optional_verdict(similarity.ax)),
        ('network', similarity.network, _optional_verdict(similarity.network)),
        ('endpoint', similarity.endpoint, _optional_verdict(similarity.endpoint)),
    ]
    for name, score, verdict in rows:
        rendered_score = '' if score is None else f'{score:.3f}'
        table.add_row(name, rendered_score, verdict)

    return table


def _optional_verdict(score: float | None) -> str:
    return 'not carried by both' if score is None else ''


__all__ = ['coerce_fingerprint', 'fingerprint_table']
