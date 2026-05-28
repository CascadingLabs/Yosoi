"""Smoke test for explicit selector cache health states.

This demonstrates the CAS-77 cache model behavior without touching your real
``.yosoi`` directory:

- active selector payloads still round-trip as selectors
- explicit inactive snapshots stay in the cache but are omitted from selector
  payloads used for extraction/verification
- legacy ``primary: "NA"`` snapshots load as ``status="absent"``
- cache summaries expose health counts without parsing selector values

Run:
    uv run python examples/selector_cache_health_smoke.py
"""

from __future__ import annotations

import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

warnings.filterwarnings(
    'ignore',
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.",
    category=UserWarning,
)

from yosoi.models.snapshot import SelectorSnapshot, SnapshotStatus
from yosoi.storage.persistence import SelectorStorage


def isolated_storage(root: Path) -> SelectorStorage:
    """Build SelectorStorage pointed at a temporary smoke directory."""
    storage = SelectorStorage.__new__(SelectorStorage)
    storage.storage_dir = str(root / 'selectors')
    storage.content_dir = str(root / 'content')
    Path(storage.storage_dir).mkdir(parents=True, exist_ok=True)
    Path(storage.content_dir).mkdir(parents=True, exist_ok=True)
    return storage


def main() -> None:
    console = Console()
    now = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory(prefix='yosoi-cache-health-') as tmp:
        storage = isolated_storage(Path(tmp))
        storage.save_snapshots(
            'https://example.com/product/1',
            {
                'title': SelectorSnapshot(primary='h1.product-title', discovered_at=now),
                'author': SelectorSnapshot(
                    discovered_at=now,
                    status=SnapshotStatus.ABSENT,
                    status_reason='field not present on this domain',
                ),
                'price': SelectorSnapshot(
                    discovered_at=now,
                    status=SnapshotStatus.DISCOVERY_FAILED,
                    status_reason='model returned no usable selector',
                ),
                'rating': SelectorSnapshot(
                    discovered_at=now,
                    status=SnapshotStatus.VERIFICATION_FAILED,
                    status_reason='candidate selector matched no elements',
                ),
                'legacy_absent': SelectorSnapshot(primary='NA', discovered_at=now),
            },
        )

        snapshots = storage.load_snapshots('example.com') or {}
        selectors = storage.load_selectors('example.com') or {}
        summary = storage.get_summary()
        health = summary['domains'][0]['health'] if summary['domains'] else {}

        console.print(
            Panel.fit(
                '[bold]Selector Cache Health Smoke[/bold]\ntemporary cache only; no real .yosoi files are modified',
                border_style='cyan',
            )
        )

        snapshot_table = Table(title='Snapshot Health')
        snapshot_table.add_column('field')
        snapshot_table.add_column('status')
        snapshot_table.add_column('selector payload')
        snapshot_table.add_column('reason')
        for field_name, snapshot in sorted(snapshots.items()):
            payload = selectors.get(field_name)
            snapshot_table.add_row(
                field_name,
                snapshot.status.value,
                repr(payload) if payload else '[dim]omitted[/dim]',
                snapshot.status_reason or '',
            )
        console.print(snapshot_table)

        health_table = Table(title='Summary Health Counts')
        health_table.add_column('status')
        health_table.add_column('count', justify='right')
        for status in SnapshotStatus:
            health_table.add_row(status.value, str(health.get(status.value, 0)))
        console.print(health_table)

        ok = (
            selectors == {'title': {'primary': 'h1.product-title'}}
            and snapshots['legacy_absent'].status == SnapshotStatus.ABSENT
            and snapshots['legacy_absent'].primary is None
            and health.get('active') == 1
            and health.get('absent') == 2
            and health.get('discovery_failed') == 1
            and health.get('verification_failed') == 1
        )
        if not ok:
            console.print(Panel.fit('[bold red]FAIL[/bold red] cache health smoke detected a regression'))
            raise SystemExit(1)

        console.print(
            Panel.fit(
                '[bold green]PASS[/bold green] inactive cache entries are explicit health states, '
                'not fake selector values',
                border_style='green',
            )
        )


if __name__ == '__main__':
    main()
