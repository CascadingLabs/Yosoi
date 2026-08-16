"""A page whose repeats nest three deep, for stressing multi-hop navigation.

One collapsed region is a zoom. Three nested collapsed regions are a *route*, and routes are
where an address space either composes or quietly stops meaning anything: the pruner descends
into one exemplar per region, so everything an agent learns about depth 3 is learned through
addresses minted while looking at depth 1.

    main#app
    └── section.dept          xD   keyed by id
        └── ul > li.team      xT   keyed by id and data-team
            └── table > tbody > tr.row   xR   keyed by id

DxTxR leaf rows exist; the index is expected to describe them with a handful of entries and let
navigation reach any one of them. Pure function of its arguments.
"""

from __future__ import annotations


def render_nested_page(departments: int = 4, teams: int = 5, rows: int = 6) -> bytes:
    """Render a page with `departments * teams * rows` leaf records in nested repeats."""
    if min(departments, teams, rows) < 2:
        raise ValueError('every level needs at least two members to form a repeat region')

    sections = ''.join(_department(index, teams, rows) for index in range(1, departments + 1))
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        f'<meta name="leaf-count" content="{departments * teams * rows}">\n'
        '<title>Nested inventory</title>\n'
        '</head>\n'
        '<body>\n'
        '<main id="app">\n'
        '<h1 id="page-heading">Nested inventory</h1>\n'
        f'{sections}'
        '</main>\n'
        '</body>\n'
        '</html>\n'
    ).encode()


def _department(index: int, teams: int, rows: int) -> str:
    """Render one department section and the teams beneath it."""
    members = ''.join(_team(index, team, rows) for team in range(1, teams + 1))
    return (
        f'<section id="dept-{index}" class="dept" data-dept="{index}">'
        f'<h2 id="dept-{index}-heading">Department {index}</h2>'
        f'<ul id="teams-{index}">{members}</ul>'
        '</section>'
    )


def _team(department: int, team: int, rows: int) -> str:
    """Render one team and its table of records."""
    key = f'{department}-{team}'
    records = ''.join(_row(key, row) for row in range(1, rows + 1))
    return (
        f'<li id="team-{key}" class="team" data-team="{key}">'
        f'<h3 id="team-{key}-heading">Team {key}</h3>'
        f'<table id="grid-{key}"><tbody id="rows-{key}">{records}</tbody></table>'
        '</li>'
    )


def _row(team_key: str, row: int) -> str:
    """Render one leaf record, uniquely identified and uniquely contented."""
    key = f'{team_key}-{row}'
    return (
        f'<tr id="row-{key}" class="row" data-row="{key}">'
        f'<td class="cell-part">Part {key}</td>'
        f'<td class="cell-count">{row * 4}</td>'
        '</tr>'
    )


__all__ = ['render_nested_page']
