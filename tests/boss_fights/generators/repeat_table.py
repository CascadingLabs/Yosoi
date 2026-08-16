"""A deterministic table of N identically shaped rows.

The shape is chosen to be the honest hard case for MDR-style collapse:

* the rows are contiguous siblings of one shape, so they *must* collapse;
* each row carries a durable `id` and a `data-*` key, so every member must come back from
  `expand` with `stable=True` rather than by position;
* row content is unique, so a text-digest key would also be unique — the reducer never gets
  to look correct by accident of duplicate content;
* the `<thead>` row has a different child shape, so a reducer that keys on the parent tag
  instead of the skeleton would over-collapse and fail the member count.

Pure function of `rows`: same argument, byte-identical output, no clock and no randomness.
"""

from __future__ import annotations

_COLUMNS = ('index', 'name', 'amount')


def render_repeat_table(rows: int) -> bytes:
    """Render a document whose body is one table of `rows` identically shaped rows."""
    if rows < 1:
        raise ValueError('a repeat-table workload needs at least one row')

    header = ''.join(f'<th class="col-{column}" scope="col">{column.title()}</th>' for column in _COLUMNS)
    body = ''.join(_row(ordinal) for ordinal in range(1, rows + 1))
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        f'<meta name="row-count" content="{rows}">\n'
        f'<title>Generated repeat table — {rows} rows</title>\n'
        '</head>\n'
        '<body>\n'
        '<main id="content">\n'
        '<h1 id="heading">Generated repeat table</h1>\n'
        '<table id="ledger">\n'
        f'<thead><tr class="head-row">{header}</tr></thead>\n'
        f'<tbody id="rows">{body}</tbody>\n'
        '</table>\n'
        '</main>\n'
        '</body>\n'
        '</html>\n'
    ).encode()


def _row(ordinal: int) -> str:
    """Render one row, uniquely identified and uniquely contented."""
    key = f'{ordinal:06d}'
    return (
        f'<tr id="row-{key}" class="entry" data-row-key="k-{key}">'
        f'<td class="cell-index">{ordinal}</td>'
        f'<td class="cell-name">Record {key}</td>'
        f'<td class="cell-amount">{ordinal * 7 % 1000}.00</td>'
        '</tr>'
    )


__all__ = ['render_repeat_table']
