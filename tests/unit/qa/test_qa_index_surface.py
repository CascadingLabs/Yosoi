from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import yosoi as ys
from yosoi.integrations.qa_index_mcp import (
    QA_INDEX_SERVER_NAME,
    QA_INDEX_TOOL_IDS,
    QA_INDEX_TOOL_NAMES,
    build_server,
    qa_index_server_command,
    qa_index_server_spec,
)
from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.html_tree import parse, skeleton_signature
from yosoi.observations.index.addressing import ref_id
from yosoi.observations.index.inspect import InspectionBudget
from yosoi.observations.models.artifact import EvidenceKind, Sensitivity
from yosoi.observations.models.index import IndexEntry, ObservationIndex
from yosoi.observations.models.snapshot import CaptureCapability, CaptureProfile, ObservationSnapshot
from yosoi.observations.models.view import RegionRef
from yosoi.qa.index import QA_INDEX_LIMITS, IndexSession
from yosoi.qa.tools import DiffArgs, ExpandArgs, IndexQAToolHandler, InspectArgs, OverviewArgs, UnwiredQAToolHandler

_CAPTURED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _evidence(
    html: str,
    snapshot_id: str,
    store: MemoryArtifactStore,
    *,
    sensitivity: Sensitivity = Sensitivity.MODEL_SAFE,
):
    artifact = store.put(
        snapshot_id=snapshot_id,
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=html.encode(),
        sensitivity=sensitivity,
    )
    snapshot = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id=snapshot_id,
        requested_profile=CaptureProfile.HTTP_STATIC,
        artifacts=(artifact,),
        capabilities=(
            CaptureCapability(kind=EvidenceKind.SOURCE_HTML, available=True),
            CaptureCapability(kind=EvidenceKind.AX_TREE, available=False, reason='static capture has no AX tree'),
        ),
        captured_at=_CAPTURED_AT,
    )
    _, tree = parse(html.encode())
    region_locator = '//*[@id="main"]#anchor=id%3Dmain'
    child_shape = skeleton_signature(tree.xpath('//*[@id="main"]')[0][0])
    region_ref = RegionRef(
        snapshot_id=snapshot_id,
        artifact_sha256=artifact.sha256,
        modality=EvidenceKind.SOURCE_HTML,
        locator=f'{region_locator}&shape={child_shape}',
    )
    entry = IndexEntry(
        ordinal=0,
        ref=region_ref,
        label='div',
        summary='main region',
        coverage={'observed': 2, 'declared': 2, 'complete': True},
        ref_id=ref_id(region_ref.modality, region_ref.locator),
    )
    return (
        snapshot,
        artifact,
        ObservationIndex(
            snapshot_id=snapshot_id, sources=(artifact,), modalities=(EvidenceKind.SOURCE_HTML,), entries=(entry,)
        ),
        region_ref,
    )


def _session_pair():
    store = MemoryArtifactStore()
    before, before_artifact, before_index, region = _evidence(
        '<html><body><div id="main"><p>A</p><p>B</p></div></body></html>', 'before', store
    )
    after, _, after_index, _ = _evidence(
        '<html><body><div id="main"><p>A</p><p>C</p></div></body></html>', 'after', store
    )
    after_index = after_index.model_copy(
        update={'entries': (after_index.entries[0].model_copy(update={'summary': 'changed'}),)}
    )
    session = asyncio.run(
        ys.index(store=store, snapshot=before, observation_index=before_index, related={'after': (after, after_index)})
    )
    return store, before, before_artifact, before_index, region, session


def test_session_composes_all_four_production_pruners() -> None:
    from yosoi.observations.index.compiler import ObservationIndexCompiler
    from yosoi.observations.models import AxNode, AxSnapshot, DomAttribute, DomNode, DomSnapshot
    from yosoi.observations.models.ax import serialize_ax_snapshot
    from yosoi.observations.models.dom import serialize_dom_snapshot
    from yosoi.observations.models.network import (
        NetworkRequest,
        NetworkTrace,
        ResourceType,
        TimingBucket,
        duplicate_key,
        serialize_network_trace,
    )
    from yosoi.observations.pruning import AxPruner, BodyPruner, DomPruner, NetworkPruner, PruningInput, PruningPolicy

    snapshot_id = 'all-four'
    html = b'<html><body><main id="main"><h1>Catalogue</h1><p>Evidence</p></main></body></html>'
    dom = serialize_dom_snapshot(
        DomSnapshot(
            snapshot_id=snapshot_id,
            root=DomNode(
                node_id='root',
                tag='html',
                children=(
                    DomNode(
                        node_id='main',
                        tag='main',
                        attributes=(DomAttribute(name='id', value='main'),),
                        text='Rendered evidence',
                    ),
                ),
            ),
        )
    )
    ax = serialize_ax_snapshot(
        AxSnapshot(
            snapshot_id=snapshot_id,
            root_id='ax-root',
            nodes=(
                AxNode(node_id='ax-root', role='document', child_ids=('button',)),
                AxNode(node_id='button', parent_id='ax-root', role='button', name='Save'),
            ),
        )
    )
    request = NetworkRequest(
        request_id='request-1',
        method='GET',
        origin='https://api.example',
        path_template='/v1/items',
        status=200,
        resource_type=ResourceType.XHR,
        mime='application/json',
        timing=TimingBucket.FAST,
        duplicate_key=duplicate_key('GET', 'https://api.example', '/v1/items', ()),
    )
    network = serialize_network_trace(NetworkTrace(snapshot_id=snapshot_id, requests=(request,)))

    store = MemoryArtifactStore()
    artifacts = tuple(
        store.put(snapshot_id=snapshot_id, kind=kind, media_type=media_type, data=data)
        for kind, media_type, data in (
            (EvidenceKind.SOURCE_HTML, 'text/html', html),
            (EvidenceKind.RENDERED_DOM, 'application/json', dom),
            (EvidenceKind.AX_TREE, 'application/json', ax),
            (EvidenceKind.NETWORK, 'application/json', network),
        )
    )
    snapshot = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id=snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=artifacts,
        captured_at=_CAPTURED_AT,
    )
    policy = PruningPolicy()
    pruners = (BodyPruner(), DomPruner(), AxPruner(), NetworkPruner())
    views = tuple(
        pruner.prune(PruningInput(source=artifact, data=data), policy)
        for pruner, artifact, data in zip(pruners, artifacts, (html, dom, ax, network), strict=True)
    )
    observation_index = ObservationIndexCompiler().compile(snapshot, views)
    session = asyncio.run(ys.index(store=store, snapshot=snapshot, observation_index=observation_index))

    capabilities = asyncio.run(session.capabilities())
    assert set(capabilities.modalities) == {'source_html', 'rendered_dom', 'ax_tree', 'network'}
    assert capabilities.operations == ('capabilities', 'status', 'overview', 'inspect', 'expand')
    overview = asyncio.run(session.overview(OverviewArgs(snapshot_id=snapshot_id, token_budget=3_000)))
    assert overview.included_refs
    for modality in (EvidenceKind.SOURCE_HTML, EvidenceKind.RENDERED_DOM, EvidenceKind.AX_TREE, EvidenceKind.NETWORK):
        entry = next(entry for entry in observation_index.entries if entry.ref.modality is modality)
        detail = asyncio.run(session.inspect(InspectArgs(ref=entry.ref)))
        assert detail.content


def test_index_session_supports_async_surface_and_exposes_missing_modalities() -> None:
    _, _, _, _, region, session = _session_pair()

    status = asyncio.run(session.status())
    assert status.ready
    assert status.snapshot_ids == ('before', 'after')
    assert 'diff' in status.capabilities.operations
    before_capabilities = status.capabilities.snapshots[0]
    assert before_capabilities.indexed_modalities == ('source_html',)
    assert before_capabilities.capture_capabilities[1].reason == 'static capture has no AX tree'

    overview = asyncio.run(session.overview(OverviewArgs(snapshot_id='before', token_budget=500)))
    assert '[0]' in overview.text
    inspected = asyncio.run(session.inspect(InspectArgs(snapshot_id='before', ordinal=0)))
    assert b'main' in inspected.content
    expanded = asyncio.run(
        session.expand(ExpandArgs(snapshot_id='before', ordinal=0, budget=InspectionBudget(max_items=1)))
    )
    assert len(expanded.members) == 1
    diff = asyncio.run(session.diff(DiffArgs(before_snapshot_id='before', after_snapshot_id='after')))
    assert diff.changes
    assert diff.truncated is False

    with pytest.raises(ValueError, match='provide ref'):
        InspectArgs(ref=region, snapshot_id='before', ordinal=0)


def test_injected_mcp_matches_the_direct_session_and_unwired_introspection_is_truthful() -> None:
    _, _, _, _, _, session = _session_pair()
    direct = asyncio.run(
        session.overview(
            OverviewArgs(snapshot_id='before', tokenizer_id='estimate/chars-per-token-4', token_budget=500)
        )
    )
    server = build_server(IndexQAToolHandler(session))
    _, status = asyncio.run(server.call_tool('status', {}))
    _, overview = asyncio.run(
        server.call_tool(
            'overview',
            {'snapshot_id': 'before', 'tokenizer_id': 'estimate/chars-per-token-4', 'token_budget': 500},
        )
    )
    _, inspected = asyncio.run(server.call_tool('inspect', {'snapshot_id': 'before', 'ordinal': 0}))
    assert status['ready'] is True
    assert overview['text'] == direct.text
    assert inspected['returned_bytes'] > 0

    unwired = build_server()
    _, unwired_status = asyncio.run(unwired.call_tool('status', {}))
    assert unwired_status['ready'] is False
    with pytest.raises(ToolError, match='not wired'):
        asyncio.run(
            unwired.call_tool(
                'overview',
                {'snapshot_id': 'before', 'tokenizer_id': 'estimate/chars-per-token-4', 'token_budget': 500},
            )
        )


def test_expand_enforces_aggregate_bytes_and_inspection_stays_utf8_serializable() -> None:
    store = MemoryArtifactStore()
    repeated = ''.join(f'<p>café item {index} with a long summary</p>' for index in range(20))
    (
        snapshot,
        _,
        observation_index,
        _,
    ) = _evidence(f'<html><body><div id="main">{repeated}</div></body></html>', 'bounded', store)
    session = IndexSession(store=store, snapshots=(snapshot,), indexes=(observation_index,))

    offset = 0
    visited: list[int] = []
    while offset < 20:
        page = asyncio.run(
            session.expand(
                ExpandArgs(
                    snapshot_id='bounded',
                    ordinal=0,
                    offset=offset,
                    budget=InspectionBudget(max_bytes=600, max_items=20, max_summary_chars=400),
                )
            )
        )
        assert page.returned_bytes <= 600
        assert page.members
        visited.extend(member.ordinal for member in page.members)
        offset += len(page.members)
    assert visited == list(range(20))
    assert page.truncated is False
    with pytest.raises(ValueError, match='too small for one'):
        asyncio.run(
            session.expand(
                ExpandArgs(
                    snapshot_id='bounded',
                    ordinal=0,
                    budget=InspectionBudget(max_bytes=1, max_items=20, max_summary_chars=400),
                )
            )
        )

    from yosoi.observations.index.inspect import _utf8_prefix

    clipped = _utf8_prefix('café'.encode(), 4)
    assert clipped == b'caf'
    clipped.decode('utf-8')


def test_qa_limits_are_hard() -> None:
    with pytest.raises(ValueError, match='less than or equal'):
        OverviewArgs(snapshot_id='s', tokenizer_id='t', token_budget=QA_INDEX_LIMITS.overview_tokens + 1)
    with pytest.raises(ValueError, match='exceeds QA ceiling'):
        InspectArgs(snapshot_id='s', ordinal=0, budget={'max_bytes': QA_INDEX_LIMITS.inspect_bytes + 1})
    with pytest.raises(ValueError, match='restricted'):
        ExpandArgs(snapshot_id='s', ordinal=0, budget={'allow_restricted': True})
    with pytest.raises(ValueError, match='less than or equal'):
        DiffArgs(
            before_snapshot_id='a',
            after_snapshot_id='b',
            limit=QA_INDEX_LIMITS.diff_page_items + 1,
        )


def test_session_rejects_restricted_sources_and_modality_lies() -> None:
    restricted_store = MemoryArtifactStore()
    restricted_snapshot, _, restricted_index, _ = _evidence(
        '<html><body><div id="main"><p>secret</p><p>secret</p></div></body></html>',
        'restricted',
        restricted_store,
        sensitivity=Sensitivity.RESTRICTED,
    )
    with pytest.raises(PermissionError, match='restricted'):
        IndexSession(
            store=restricted_store,
            snapshots=(restricted_snapshot,),
            indexes=(restricted_index,),
        )

    store, before, _, before_index, _, _ = _session_pair()
    lied = before_index.model_copy(update={'modalities': (EvidenceKind.NETWORK,)})
    with pytest.raises(ValueError, match='modalities'):
        IndexSession(store=store, snapshots=(before,), indexes=(lied,))

    entry = before_index.entries[0]
    wrong_ref = entry.ref.model_copy(update={'modality': EvidenceKind.NETWORK})
    wrong_entry = entry.model_copy(update={'ref': wrong_ref, 'ref_id': None})
    wrong_index = before_index.model_copy(update={'entries': (wrong_entry,)})
    with pytest.raises(ValueError, match='entry modality'):
        IndexSession(store=store, snapshots=(before,), indexes=(wrong_index,))


def test_session_construction_rejects_ambiguous_incomplete_or_forged_inputs() -> None:
    store, before, artifact, before_index, _, _ = _session_pair()
    with pytest.raises(ValueError, match='duplicate snapshot ids'):
        IndexSession(store=store, snapshots=(before, before), indexes=(before_index, before_index))

    forged = artifact.model_copy(update={'media_type': 'application/json'})
    forged_index = before_index.model_copy(update={'sources': (forged,)})
    with pytest.raises(ValueError, match='declared by its snapshot'):
        IndexSession(store=store, snapshots=(before,), indexes=(forged_index,))

    with pytest.raises(ValueError, match='missing or failed integrity'):
        IndexSession(store=MemoryArtifactStore(), snapshots=(before,), indexes=(before_index,))

    with pytest.raises(ValueError, match='mapping keys'):
        asyncio.run(
            ys.index(
                store=store,
                snapshot=before,
                observation_index=before_index,
                related={'not-before': (before, before_index)},
            )
        )


def test_mcp_server_spec_is_host_neutral_and_uses_prefixed_allowed_ids() -> None:
    status = asyncio.run(UnwiredQAToolHandler().status())
    assert status.ready is False
    assert status.capabilities.operations == ('capabilities', 'status')
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    overview_schema = tools['overview'].inputSchema
    assert overview_schema['properties']['tokenizer_id']['default'] == 'estimate/chars-per-token-4'
    assert overview_schema['properties']['token_budget']['default'] == 1_000
    inspect_schema = tools['inspect'].inputSchema
    assert 'RegionRef' in inspect_schema['$defs']
    assert 'allow_restricted' not in inspect_schema['properties']

    spec = qa_index_server_spec()
    assert spec['name'] == QA_INDEX_SERVER_NAME
    assert spec['tools'] == QA_INDEX_TOOL_NAMES
    assert spec['allowed_tools'] == QA_INDEX_TOOL_IDS
    assert all(tool.startswith(f'mcp__{QA_INDEX_SERVER_NAME}__') for tool in QA_INDEX_TOOL_IDS)
    assert qa_index_server_command()[0]
