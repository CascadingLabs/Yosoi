"""One page and a set of deliberate edits to it, for measuring reference stability.

Address stability cannot be argued from a single snapshot — a locator that never gets compared
to a second capture of the same page is stable by assumption. So this generator emits the same
document under named mutations, each chosen because it breaks a different addressing strategy:

    section_above    inserts a sibling near the top of <body>; breaks every root-absolute path
    row_inserted     inserts a record mid-list; breaks positional member addressing
    rows_reordered   reverses the records; breaks positional member addressing differently
    column_added     adds a cell to every row; changes the repeat SHAPE
    prose_reworded   rewrites text; breaks text-digest keys, must not break structural anchors
    class_restyled   renames class values; breaks class-tier anchors, must not break id-tier

The base page carries every anchor tier on purpose — an `id` container, a `data-*` row hook,
class-only elements, an attribute-only `<meta>`, a bare `<title>` reachable only by tag, and an
attribute-free subtree that nothing durable can anchor — the `<span>` appears twice precisely so
that a tag anchor cannot rescue it.

Pure function of `mutation`: same name, byte-identical output.
"""

from __future__ import annotations

MUTATIONS = (
    'base',
    'section_above',
    'row_inserted',
    'rows_reordered',
    'column_added',
    'prose_reworded',
    'class_restyled',
)

_ROWS = (('A-1', 'Widget', 4), ('A-2', 'Sprocket', 11), ('A-3', 'Flange', 2))


def render_mutable_page(mutation: str) -> bytes:
    """Render the ledger page under one named mutation."""
    if mutation not in MUTATIONS:
        raise ValueError(f'unknown mutation {mutation!r}; expected one of {MUTATIONS}')

    rows = list(_ROWS)
    if mutation == 'row_inserted':
        rows.insert(1, ('A-9', 'Gasket', 7))
    if mutation == 'rows_reordered':
        rows.reverse()

    banner = (
        '<section class="banner"><p>Scheduled maintenance Sunday.</p></section>\n'
        if (mutation == 'section_above')
        else ''
    )
    heading = 'Revised quarterly ledger' if mutation == 'prose_reworded' else 'Quarterly ledger'
    first_note = 'Amounts restated in full.' if mutation == 'prose_reworded' else 'Amounts are provisional.'
    title_class = 'title-lg' if mutation == 'class_restyled' else 'report-title'
    notes_class = 'notes notes--v2' if mutation == 'class_restyled' else 'notes'

    body = ''.join(_row(sku, name, quantity, priced=mutation == 'column_added') for sku, name, quantity in rows)
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="description" content="Quarterly ledger of parts on hand">\n'
        '<title>Quarterly ledger</title>\n'
        '</head>\n'
        '<body>\n'
        f'{banner}'
        '<header class="masthead"><p>Parts <span>inventory</span></p></header>\n'
        '<main id="report">\n'
        f'<h1 class="{title_class}">{heading}</h1>\n'
        f'<div class="{notes_class}"><p>{first_note}</p><p>Figures exclude tax.</p></div>\n'
        '<div><span>Unanchorable</span></div>\n'
        '<table id="ledger">\n'
        f'<tbody id="rows">{body}</tbody>\n'
        '</table>\n'
        '</main>\n'
        '</body>\n'
        '</html>\n'
    ).encode()


def _row(sku: str, name: str, quantity: int, *, priced: bool) -> str:
    """Render one ledger row, optionally with the extra column that changes its shape."""
    price = f'<td class="cell-price">{quantity * 3}.00</td>' if priced else ''
    return (
        f'<tr id="row-{sku}" data-sku="{sku}" class="entry">'
        f'<td class="cell-name">{name}</td>'
        f'<td class="cell-qty">{quantity}</td>'
        f'{price}'
        '</tr>'
    )


__all__ = ['MUTATIONS', 'render_mutable_page']
