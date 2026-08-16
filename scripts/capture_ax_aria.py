"""Capture the controlled ARIA fixture's raw accessibility tree through VoidCrawl.

Run from the repository root:

    uv run python scripts/capture_ax_aria.py

The fixture is served over loopback rather than opened as `file://`, so the capture goes through
the same navigation path a real page does. Both modalities of the same page state are frozen — the
raw AX tree and the rendered DOM — because the boss fight's claim is a CROSS-MODAL one: a control
that is plainly there in the DOM and simply gone from the accessibility tree.

Digests are written to `capture_manifest.json`; the tests assert them and never touch a network.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import http.server
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from voidcrawl import BrowserPool, PoolConfig

from scripts.capture_dom_todomvc import CAPTURE_JS
from yosoi.observations.models.ax import (
    AxCapability,
    AxCapabilityKind,
    AxNode,
    AxProperty,
    AxRelation,
    AxRelationKind,
    AxSnapshot,
    serialize_ax_snapshot,
)
from yosoi.observations.models.dom import DomSnapshot, serialize_dom_snapshot

OUTPUT = Path('tests/boss_fights/ax/aria_widgets')
FIXTURE = 'fixture.html'
PORT = 8731
"""Fixed loopback port, so a re-capture differs only where the page differs.

The browser records the document URL as a property of the AX root, so an ephemeral port would
put a random number inside the canonical artifact and change its digest on every capture for a
reason that has nothing to do with the page.
"""
SNAPSHOT_ID = 'aria-widgets-ax'
DOM_SNAPSHOT_ID = 'aria-widgets-dom'

_RELATION_KINDS = {kind.value: kind for kind in AxRelationKind}


class CaptureManifest(BaseModel):
    """Small provenance record written beside frozen captures."""

    source_url: str
    captured_at: str
    status_code: int
    ax_node_count: int
    files: dict[str, str]


def _text(value: Any) -> str:
    """Flatten one CDP `AXValue` to text, so a property is comparable and printable."""
    if not isinstance(value, dict):
        return '' if value is None else str(value)
    inner = value.get('value')
    if isinstance(inner, bool):
        return 'true' if inner else 'false'
    if inner is None:
        return ''
    return str(inner)


def _relations(raw: dict[str, Any], ax_by_backend: dict[int, str]) -> tuple[AxRelation, ...]:
    """Lift relationship properties out of `properties` and into explicit edges."""
    edges: list[AxRelation] = []
    for prop in raw.get('properties') or ():
        kind = _RELATION_KINDS.get(prop.get('name', ''))
        if kind is None:
            continue
        related = (prop.get('value') or {}).get('relatedNodes') or ()
        for target in related:
            backend = target.get('backendDOMNodeId')
            edges.append(
                AxRelation(
                    kind=kind,
                    target_node_id=ax_by_backend.get(backend) if isinstance(backend, int) else None,
                    target_backend_dom_node_id=backend if isinstance(backend, int) else None,
                    target_text=target.get('idref') or target.get('text') or '',
                )
            )
        if not related:
            # A relationship property with no resolvable target is still the page's own claim
            # that the relationship exists. Dropping it would erase the defect.
            edges.append(AxRelation(kind=kind, target_text=_text(prop.get('value')) or kind.value))
    return tuple(edges)


def _properties(raw: dict[str, Any]) -> tuple[AxProperty, ...]:
    """Keep the non-relationship properties, values flattened to text."""
    return tuple(
        AxProperty(name=prop['name'], value=_text(prop.get('value')))
        for prop in raw.get('properties') or ()
        if prop.get('name') and prop['name'] not in _RELATION_KINDS
    )


def _deduplicate(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop byte-identical repeats of one node id, and refuse contradictory ones.

    A measured producer quirk, not a defensive flourish: `Accessibility.getFullAXTree` returned
    187 entries for 178 nodes on this fixture, the extra nine being exact duplicates of
    negative-id `InlineTextBox` list markers ("• "). An exact repeat carries no information, so
    collapsing it loses nothing; two entries sharing an id and disagreeing would mean the
    producer's graph is not a graph, and that must fail loudly rather than pick a winner.
    """
    seen: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node['nodeId']
        previous = seen.get(node_id)
        if previous is None:
            seen[node_id] = node
        elif json.dumps(previous, sort_keys=True) != json.dumps(node, sort_keys=True):
            raise RuntimeError(f'AX producer reported node {node_id!r} twice with different content')
    return list(seen.values())


def to_snapshot(raw_nodes: list[dict[str, Any]], snapshot_id: str) -> AxSnapshot:
    """Convert raw CDP AX nodes into the canonical artifact, before any compaction."""
    nodes = _deduplicate(raw_nodes)
    present = {node['nodeId'] for node in nodes}
    ax_by_backend = {
        node['backendDOMNodeId']: node['nodeId'] for node in nodes if isinstance(node.get('backendDOMNodeId'), int)
    }
    roots = [node for node in nodes if not node.get('parentId')]
    if len(roots) != 1:
        raise RuntimeError(f'expected one AX root, got {len(roots)}')

    converted = tuple(
        AxNode(
            node_id=node['nodeId'],
            parent_id=node.get('parentId'),
            # Child ids are filtered against what the producer actually returned: a childId naming
            # a node absent from the payload is the producer's truncation, and the artifact must
            # describe the graph it holds rather than one it cannot.
            child_ids=tuple(child for child in node.get('childIds') or () if child in present),
            role=_text(node.get('role')),
            name=_text(node.get('name')),
            value=_text(node.get('value')),
            description=_text(node.get('description')),
            properties=_properties(node),
            ignored=bool(node.get('ignored')),
            ignored_reasons=tuple(
                AxProperty(name=reason['name'], value=_text(reason.get('value')))
                for reason in node.get('ignoredReasons') or ()
                if reason.get('name')
            ),
            relations=_relations(node, ax_by_backend),
            backend_dom_node_id=node.get('backendDOMNodeId'),
        )
        for node in nodes
    )
    return AxSnapshot(
        snapshot_id=snapshot_id,
        root_id=roots[0]['nodeId'],
        nodes=converted,
        capabilities=(
            AxCapability(kind=AxCapabilityKind.IGNORED_NODES, available=True),
            AxCapability(kind=AxCapabilityKind.PROPERTIES, available=True),
            AxCapability(kind=AxCapabilityKind.RELATIONSHIPS, available=True),
            AxCapability(
                kind=AxCapabilityKind.DOM_CORRELATION,
                available=False,
                reason='backendDOMNodeId is captured, but the rendered-DOM artifact addresses '
                'nodes by JS-walk path ids, so no join key is shared between the two modalities',
            ),
            AxCapability(
                kind=AxCapabilityKind.VISIBLE_TEXT_COVERAGE,
                available=False,
                reason='the browser omits from the accessibility tree whatever it judges '
                'non-semantic, so absence here is never proof the visible page lacks it',
            ),
            AxCapability(
                kind=AxCapabilityKind.FRAME_TRAVERSAL,
                available=False,
                reason='only the main frame tree was requested from the producer',
            ),
        ),
    )


def _serve(directory: Path) -> http.server.ThreadingHTTPServer:
    """Serve the fixture directory on an ephemeral loopback port."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _dom_snapshot(payload: object, snapshot_id: str) -> bytes:
    """Bind the shared rendered-DOM capture payload to its own snapshot identity."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise TypeError(f'expected DOM object from browser, got {type(payload).__name__}')
    payload['snapshot_id'] = snapshot_id
    return serialize_dom_snapshot(DomSnapshot.model_validate(payload))


def _write(files: dict[str, bytes], *, url: str, status_code: int, ax_node_count: int) -> None:
    """Freeze artifacts and their digests after the browser session closes."""
    artifacts = OUTPUT / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for name, data in files.items():
        (artifacts / name).write_bytes(data)
        digests[name] = hashlib.sha256(data).hexdigest()
    manifest = CaptureManifest(
        source_url=url,
        captured_at=datetime.now(timezone.utc).isoformat(),
        status_code=status_code,
        ax_node_count=ax_node_count,
        files=digests,
    )
    (OUTPUT / 'capture_manifest.json').write_text(manifest.model_dump_json(indent=2) + '\n', encoding='utf-8')


async def main() -> None:
    """Capture the ARIA fixture's AX tree and rendered DOM with one live VoidCrawl tab."""
    server = _serve(OUTPUT)
    url = f'http://127.0.0.1:{PORT}/{FIXTURE}'
    try:
        async with BrowserPool(PoolConfig()) as pool, pool.acquire() as tab:
            response = await tab.goto(url)
            raw_nodes = await tab.get_full_ax_tree()
            dom_payload = await tab.evaluate_js(CAPTURE_JS)
        if response.status_code is None:
            raise RuntimeError('ARIA fixture capture returned no HTTP status')
        snapshot = to_snapshot(list(raw_nodes), SNAPSHOT_ID)
        _write(
            {
                'ax_tree.json': serialize_ax_snapshot(snapshot),
                'rendered_dom.json': _dom_snapshot(dom_payload, DOM_SNAPSHOT_ID),
            },
            url=f'served locally from {OUTPUT / FIXTURE}',
            status_code=response.status_code,
            ax_node_count=snapshot.observed_node_count,
        )
    finally:
        server.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
