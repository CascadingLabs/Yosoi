"""Smoke test for same-domain selector discovery race coordination.

Scenario:
    Three fresh qscrape URLs from the same domain ask for the same contract at
    the same time. Yosoi should not spend LLM compute three times per field.

What this demonstrates:
    - A shared DiscoveryBus elects one leader per domain+field signature.
    - Other same-domain workers wait for that field result and reuse it.
    - A per-domain write lock serializes the final selector-cache writes only.

This is a scheduler smoke. It uses a fake delayed field agent so it needs no
network, browser, or LLM keys, and it prints the same counters you care about.

Run:
    uv run python examples/tutorial/selector_discovery_race_smoke.py
"""

from __future__ import annotations

import asyncio
import time
import warnings
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

warnings.filterwarnings(
    'ignore',
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.",
    category=UserWarning,
)

import yosoi as ys
from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator
from yosoi.models.contract import Contract
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.models.snapshot import SelectorSnapshot

URLS = [
    'https://qscrape.dev/l2/eshop/products/alpha',
    'https://qscrape.dev/l2/eshop/products/bravo',
    'https://qscrape.dev/l2/eshop/products/charlie',
]

HTML = """
<html>
  <body>
    <article class="product-card">
      <h1 class="product-name">Smoke Product</h1>
      <span class="price">$42.00</span>
    </article>
  </body>
</html>
"""


class Product(Contract):
    """Small qscrape-style product contract."""

    name: str = ys.Title(description='Product name')
    price: float = ys.Price(description='Product price as a number')


@dataclass
class RecordingStorage:
    """Tiny storage test double that records cache reads/writes for terminal output."""

    read_count: int = 0
    write_count: int = 0
    writes_in_flight: int = 0
    peak_writes_in_flight: int = 0
    saved_fields: list[list[str]] = field(default_factory=list)

    async def load_snapshots(self, _domain: str) -> dict[str, SelectorSnapshot] | None:
        self.read_count += 1
        return None

    async def load_selectors(self, _domain: str) -> dict[str, Any] | None:
        self.read_count += 1
        return None

    async def save_snapshots(self, _url: str, snapshots: dict[str, SelectorSnapshot]) -> str:
        self.write_count += 1
        self.writes_in_flight += 1
        self.peak_writes_in_flight = max(self.peak_writes_in_flight, self.writes_in_flight)
        try:
            self.saved_fields.append(sorted(snapshots))
            return 'memory://selectors_qscrape_dev.json'
        finally:
            self.writes_in_flight -= 1

    def save_selectors(self, _url: str, _selectors: dict[str, Any], *, _verified: bool = False) -> str:
        raise AssertionError('orchestrator should persist snapshots explicitly')


class CountingAgent:
    """Fake field agent that behaves like a slow LLM call and records compute."""

    def __init__(self, calls: Counter[str], leaders: list[str]) -> None:
        self._calls = calls
        self._leaders = leaders

    async def discover_field(
        self,
        field_name: str,
        _field_description: str,
        _discovery_input: Any,
        _target_level: SelectorLevel,
        _is_container: bool = False,
        _feedback: Any = None,
    ) -> FieldSelectors | None:
        self._calls[field_name] += 1
        self._leaders.append(field_name)
        await asyncio.sleep(0.15)
        if field_name == 'name':
            return FieldSelectors(primary='.product-name')
        if field_name == 'price':
            return FieldSelectors(primary='.price')
        if field_name == 'root':
            return FieldSelectors(primary='.product-card')
        return None


async def run_one(
    url: str,
    bus: DiscoveryBus,
    write_lock: asyncio.Lock,
    storage: RecordingStorage,
    calls: Counter[str],
    leaders: list[str],
) -> tuple[str, dict[str, dict[str, Any]] | None, float]:
    orchestrator = DiscoveryOrchestrator(
        contract=Product,
        llm_config=LLMConfig(provider='groq', model_name='fake-smoke-model', api_key='unused'),
        storage=storage,  # type: ignore[arg-type]
        target_level=SelectorLevel.CSS,
        max_concurrent=3,
        bus=bus,
        write_lock=write_lock,
        console=Console(quiet=True),
    )
    orchestrator._agent = CountingAgent(calls, leaders)  # type: ignore[assignment]

    started = time.perf_counter()
    selectors = await orchestrator.discover_selectors(HTML, url=url, force=True)
    return url, selectors, (time.perf_counter() - started) * 1000


async def main() -> None:
    console = Console()
    bus = DiscoveryBus()
    write_lock = asyncio.Lock()
    storage = RecordingStorage()
    calls: Counter[str] = Counter()
    leaders: list[str] = []

    console.print(
        Panel.fit(
            '[bold]Selector Discovery Race Smoke[/bold]\n'
            '3 fresh qscrape.dev URLs, same Product contract, same domain cache bucket',
            border_style='cyan',
        )
    )

    results = await asyncio.gather(
        *(run_one(url, bus, write_lock, storage, calls, leaders) for url in URLS),
    )

    expected_fields = {'name', 'price', 'root'}
    expected_compute = dict.fromkeys(expected_fields, 1)
    ok_compute = all(calls[field_name] == 1 for field_name in expected_fields)
    ok_results = all(selectors is not None and expected_fields <= set(selectors) for _url, selectors, _ms in results)
    ok_writes = storage.peak_writes_in_flight == 1 and storage.write_count == len(URLS)

    url_table = Table(title='Worker Results')
    url_table.add_column('URL')
    url_table.add_column('selector fields')
    url_table.add_column('elapsed', justify='right')
    for url, selectors, elapsed_ms in results:
        url_table.add_row(url, ', '.join(sorted(selectors or {})), f'{elapsed_ms:.0f} ms')
    console.print(url_table)

    compute_table = Table(title='LLM Compute Calls Avoided')
    compute_table.add_column('field')
    compute_table.add_column('actual fake LLM calls', justify='right')
    compute_table.add_column('naive calls without bus', justify='right')
    compute_table.add_column('status')
    for field_name in sorted(expected_fields):
        actual = calls[field_name]
        status = '[green]shared once[/green]' if actual == expected_compute[field_name] else '[red]duplicated[/red]'
        compute_table.add_row(field_name, str(actual), str(len(URLS)), status)
    console.print(compute_table)

    lock_table = Table(title='Cache Write Coordination')
    lock_table.add_column('metric')
    lock_table.add_column('value', justify='right')
    lock_table.add_row('final cache writes', str(storage.write_count))
    lock_table.add_row('peak simultaneous writes', str(storage.peak_writes_in_flight))
    lock_table.add_row('saved field sets', '; '.join(','.join(fields) for fields in storage.saved_fields))
    console.print(lock_table)

    if not (ok_compute and ok_results and ok_writes):
        console.print(Panel.fit('[bold red]FAIL[/bold red] selector discovery race coordination regressed'))
        raise SystemExit(1)

    avoided = (len(URLS) - 1) * len(expected_fields)
    console.print(
        Panel.fit(
            f'[bold green]PASS[/bold green] one discovery per field, {avoided} duplicate fake LLM calls avoided; '
            'cache writes stayed serialized',
            border_style='green',
        )
    )


if __name__ == '__main__':
    asyncio.run(main())
