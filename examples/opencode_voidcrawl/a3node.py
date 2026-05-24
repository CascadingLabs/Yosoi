"""A3Node — an Assess/Act/Assert recipe that makes a browse fully replayable (CAS-13).

Once the action sequence is locked in — discovered by the MCP agent (see recipe.py)
or hand-authored like the Maps flow — it's saved per-domain and replayed
deterministically over the PyO3 binding: no agent, no LLM, no re-discovery. Each act
carries an optional `assert_min` postcondition (the third 'A'); a failed assert means
the page changed and the node should be re-discovered.

Mirrors yosoi/storage/a3node.py (per-domain JSON, replay_count, discovered_at) but
with a richer, *replayable* act schema (teleport / navigate / scroll / click) plus an
AX extraction recipe, rather than the DOM-stability {kind, cycles} triggers.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ax_extract import AxField, extract_cards

Geo = tuple[float, float, str | None, str | None]  # lat, lon, timezone, locale


class A3AssertError(RuntimeError):
    """A replayed act's postcondition failed — the page likely changed; re-discover."""


@dataclass
class Act:
    """One replayable step. `op` selects which params apply.

    teleport: (geo supplied at replay) · navigate: url · scroll: feed/item/target
    (+ assert_min postcondition) · click: role+name+nth or selector.
    """

    op: Literal['teleport', 'navigate', 'scroll', 'click']
    url: str | None = None
    feed: str | None = None
    item: str | None = None
    target: int | None = None
    assert_min: int | None = None
    role: str | None = None
    name: str | None = None
    selector: str | None = None
    nth: int = 0


@dataclass
class ExtractRecipe:
    """AX-tree extraction recipe (CAS-27): repeating card role + per-field role/pattern."""

    card_role: str
    fields: list[dict[str, Any]]  # each: {key, role, pattern?}
    skip_prefixes: list[str] = field(default_factory=list)

    def ax_fields(self) -> list[AxField]:
        return [AxField(f['key'], role=f['role'], pattern=f.get('pattern')) for f in self.fields]


@dataclass
class A3Node:
    domain: str
    task: str
    acts: list[Act]
    extract: ExtractRecipe
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    replay_count: int = 0
    last_replayed_at: str | None = None

    # ── persistence (per-domain JSON, like yosoi A3NodeStorage) ──────────────
    @staticmethod
    def _path(domain: str, storage_dir: str | Path) -> Path:
        slug = domain.replace('/', '_').replace(':', '')
        return Path(storage_dir) / f'a3node_{slug}.json'

    def save(self, storage_dir: str | Path) -> Path:
        Path(storage_dir).mkdir(parents=True, exist_ok=True)
        path = self._path(self.domain, storage_dir)
        payload = {
            'domain': self.domain,
            'task': self.task,
            'acts': [asdict(a) for a in self.acts],
            'extract': asdict(self.extract),
            'discovered_at': self.discovered_at,
            'replay_count': self.replay_count,
            'last_replayed_at': self.last_replayed_at,
        }
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return path

    @classmethod
    def load(cls, domain: str, storage_dir: str | Path) -> A3Node | None:
        path = cls._path(domain, storage_dir)
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding='utf-8'))
        return cls(
            domain=d['domain'],
            task=d['task'],
            acts=[Act(**a) for a in d['acts']],
            extract=ExtractRecipe(**d['extract']),
            discovered_at=d.get('discovered_at', ''),
            replay_count=d.get('replay_count', 0),
            last_replayed_at=d.get('last_replayed_at'),
        )


async def replay_acts(
    node: A3Node, page: Any, *, geo: Geo | None = None, nav_sleeps: tuple[float, ...] = (2.5, 3.5)
) -> None:
    """Execute the locked-in acts on a fresh page — deterministic, no agent/LLM.

    Raises A3AssertError if an act's postcondition fails (page changed → re-discover).
    """
    nav_i = 0
    for act in node.acts:
        if act.op == 'teleport':
            if geo is None:
                continue
            lat, lon, tz, locale = geo
            await page.set_geolocation(lat, lon, 50.0)
            if tz:
                await page.set_timezone(tz)
            if locale:
                await page.set_locale(locale)
        elif act.op == 'navigate':
            await page.navigate(act.url or 'about:blank')
            await asyncio.sleep(nav_sleeps[min(nav_i, len(nav_sleeps) - 1)])
            nav_i += 1
        elif act.op == 'scroll':
            count = await _scroll(page, act.feed or '', act.item or '', act.target or 0)
            if act.assert_min is not None and count < act.assert_min:
                raise A3AssertError(f'scroll {act.item!r}: {count} < {act.assert_min} — page changed, re-discover')
        elif act.op == 'click':
            if act.role:
                await page.click_by_role(act.role, act.name or '', act.nth)
            elif act.selector:
                await page.click_element(act.selector)


async def _scroll(page: Any, feed: str, item: str, target: int) -> int:
    count = -1
    for _ in range(15):
        raw = await page.evaluate_js(
            f'(()=>{{const f=document.querySelector({json.dumps(feed)});'
            f'if(!f)return -1;f.scrollTop=f.scrollHeight;'
            f'return f.querySelectorAll({json.dumps(item)}).length;}})()'
        )
        count = raw if isinstance(raw, int) else -1
        if count >= target:
            break
        await asyncio.sleep(1.3)
    return count


def extract(node: A3Node, ax_nodes: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    """Replay the AX extraction recipe over a captured accessibility tree."""
    return extract_cards(
        ax_nodes,
        card_role=node.extract.card_role,
        fields=node.extract.ax_fields(),
        skip_name_prefixes=tuple(node.extract.skip_prefixes),
    )
