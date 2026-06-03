"""CLI for the experimental reuse-hint review queue (CAS-85).

Operates over the append-only decision ledger (the flywheel artifact): list what
is pending review, promote (confirm) or reject (refute) a decision by id, or print
a tally. Scriptable — ``--json`` emits machine-readable output and promote/reject
take an id argument with no prompts, so the queue can be driven from a script as
easily as by hand.

Exposed as the ``yosoi-generalization`` console script.
"""

from __future__ import annotations

import json

import rich_click as click
from rich.table import Table

from yosoi.cli.utils import console
from yosoi.generalization.store import DecisionStore
from yosoi.generalization.trust import DecisionRecord

_COLUMNS = ('id', 'scope', 'verdict', 'trust', 'outcome', 'replay')


def _row(rec: DecisionRecord) -> dict[str, str]:
    """Flatten a decision record to the fields the CLI shows."""
    return {
        'id': rec.id,
        'scope': rec.scope.value,
        'verdict': rec.driver_verdict.value,
        'trust': rec.trust.value,
        'outcome': rec.outcome.value,
        'seed': rec.panel.seed_url,
        'replay': rec.panel.replay_url,
    }


def _resolve(decision_id: str, *, confirmed: bool) -> None:
    """Promote or reject a decision by id and report the result."""
    rec = DecisionStore().decide(decision_id, confirmed=confirmed)
    if rec is None:
        raise click.ClickException(f'unknown decision id: {decision_id}')
    console.print(f'[success]{decision_id} -> trust={rec.trust.value} outcome={rec.outcome.value}[/success]')


@click.group()
def cli() -> None:
    """Inspect and adjudicate reuse-hint decisions."""


@cli.command()
@click.option('--json', 'as_json', is_flag=True, help='Emit JSON instead of a table.')
def summary(as_json: bool) -> None:
    """Print a tally of the decision ledger (by scope, trust, outcome, queue)."""
    data = DecisionStore().summary()
    if as_json:
        click.echo(json.dumps(data, indent=2, sort_keys=True))
        return
    for key in sorted(data):
        console.print(f'{key:>22}: {data[key]}')


@cli.group()
def review() -> None:
    """Review the pending-reuse queue."""


@review.command('list')
@click.option('--json', 'as_json', is_flag=True, help='Emit JSON instead of a table.')
@click.option('--all', 'show_all', is_flag=True, help='Show every decision, not just those pending review.')
def review_list(as_json: bool, show_all: bool) -> None:
    """List decisions awaiting review (or every decision with ``--all``)."""
    store = DecisionStore()
    records = store.current() if show_all else store.pending()
    rows = [_row(r) for r in records]
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print('[success]Nothing pending review.[/success]')
        return
    table = Table(title='Reuse decisions')
    for col in _COLUMNS:
        table.add_column(col)
    for r in rows:
        table.add_row(*(r[col] for col in _COLUMNS))
    console.print(table)


@review.command('promote')
@click.argument('decision_id')
def review_promote(decision_id: str) -> None:
    """Confirm a decision: QUARANTINED -> VERIFIED."""
    _resolve(decision_id, confirmed=True)


@review.command('reject')
@click.argument('decision_id')
def review_reject(decision_id: str) -> None:
    """Reject a decision: QUARANTINED -> REJECTED."""
    _resolve(decision_id, confirmed=False)
