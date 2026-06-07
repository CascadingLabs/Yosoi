"""Human-friendly terminal display helpers for scraped data."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from rich.console import Console
from rich.table import Table
from rich.text import Text

ShowFormat = Literal['auto', 'table', 'plain', 'json']

_console = Console()
_VALID_FORMATS: set[str] = {'auto', 'table', 'plain', 'json'}


def show(
    value: Any,
    *,
    format: ShowFormat = 'auto',
    title: str | None = None,
    console: Console | None = None,
    fingerprint: object | bool | None = None,
) -> None:
    """Render scraped data or fingerprint reports in a terminal-friendly form."""
    if format not in _VALID_FORMATS:
        raise ValueError(f'Unknown show format {format!r}. Expected one of: {", ".join(sorted(_VALID_FORMATS))}.')

    con = console or _console
    if title:
        _print_line(con, title)

    if fingerprint is True or _is_page_fingerprint(value):
        from yosoi.reporting.fingerprint import fingerprint_table

        con.print(fingerprint_table(value))
        return

    if fingerprint is not None and fingerprint is not False:
        from yosoi.reporting.fingerprint import fingerprint_table

        con.print(fingerprint_table(value, compare_to=fingerprint))
        return

    if format == 'json':
        _print_line(con, json.dumps(value, indent=2, ensure_ascii=False, default=_json_default))
        return

    if format == 'plain':
        con.print(value, markup=False, soft_wrap=True)
        return

    if _render_tables(value, con):
        return

    if format == 'table':
        raise TypeError(
            'format="table" requires list[dict], dict[str, list[dict]], or dict[str, dict[str, list[dict]]].'
        )

    con.print(value, markup=False, soft_wrap=True)


def _render_tables(value: Any, console: Console) -> bool:
    if _is_records(value):
        _render_record_table(value, console)
        return True

    if not _is_table_mapping(value):
        return False

    for group, group_value in value.items():
        if _is_records(group_value):
            _print_line(console, str(group))
            _render_record_table(group_value, console)
            continue

        _print_line(console, str(group))
        for subgroup, records in group_value.items():
            _print_line(console, f'  {subgroup}')
            _render_record_table(records, console)

    return True


def _is_table_mapping(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    for group_value in value.values():
        if _is_records(group_value):
            continue
        if isinstance(group_value, Mapping) and all(_is_records(records) for records in group_value.values()):
            continue
        return False
    return True


def _render_record_table(records: Sequence[Mapping[str, Any]], console: Console) -> None:
    if not records:
        _print_line(console, '  (no rows)')
        return

    columns = _columns(records)
    table = Table(show_lines=False)
    for column in columns:
        table.add_column(str(column), overflow='fold')

    for record in records:
        table.add_row(*[_cell(record.get(column)) for column in columns])

    console.print(table)


def _columns(records: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            column = str(key)
            if column not in seen:
                columns.append(column)
                seen.add(column)
    return columns


def _cell(value: Any) -> Text:
    if value is None:
        return Text('')
    if isinstance(value, (str, int, float, bool)):
        return Text(str(value))
    return Text(json.dumps(value, ensure_ascii=False, default=_json_default))


def _is_records(value: Any) -> bool:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return False
    return all(isinstance(item, Mapping) for item in value)


def _is_page_fingerprint(value: Any) -> bool:
    return value.__class__.__name__ == 'PageFingerprint' and hasattr(value, 'similarity') and hasattr(value, 'skeleton')


def _json_default(value: Any) -> Any:
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    if hasattr(value, 'dict'):
        return value.dict()
    return str(value)


def _print_line(console: Console, text: str) -> None:
    console.print(text, markup=False, soft_wrap=True)


__all__ = ['ShowFormat', 'show']
