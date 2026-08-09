"""Offline gate for the frozen ARIA widget-matrix accessibility capture.

Every assertion here runs against bytes on disk. The capture came from a real headless browser
through VoidCrawl (`scripts/capture_ax_aria.py`); nothing in this module opens a socket.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import tomllib

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.ax_tree import ax_subtree_text
from yosoi.observations.index.addressing import ObservationAddressError, parse_address, ref_id
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.index.render import CharacterEstimator, ObservationIndexRenderer, RenderPolicy
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.ax import AxCapabilityKind, AxNode, AxSnapshot, parse_ax_snapshot, serialize_ax_snapshot
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.models.view import RegionRef
from yosoi.observations.pruning import AxPruner, DomPruner, PruningInput, PruningPolicy

ROOT = Path(__file__).parent
ARTIFACTS = ROOT / 'artifacts'
MANIFEST = tomllib.loads((ROOT / 'manifest.toml').read_text())
GROUND_TRUTH = tomllib.loads((ROOT / 'ground_truth.toml').read_text())

AX_BYTES = (ARTIFACTS / 'ax_tree.json').read_bytes()
DOM_BYTES = (ARTIFACTS / 'rendered_dom.json').read_bytes()


def _snapshot() -> AxSnapshot:
    return parse_ax_snapshot(AX_BYTES)


def _bound(snapshot_id: str | None = None):
    """Prune, compile, and bind the frozen AX capture into a walkable address space."""
    snapshot = _snapshot()
    data = AX_BYTES
    if snapshot_id is not None and snapshot_id != snapshot.snapshot_id:
        data = serialize_ax_snapshot(snapshot.model_copy(update={'snapshot_id': snapshot_id}))
    identity = snapshot_id or snapshot.snapshot_id

    store = MemoryArtifactStore()
    artifact = store.put(snapshot_id=identity, kind=EvidenceKind.AX_TREE, media_type='application/json', data=data)
    manifest = ObservationSnapshot(
        run_id='aria-widgets',
        episode_id='aria-widgets',
        snapshot_id=identity,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(artifact,),
    )
    view = AxPruner().prune(PruningInput(source=artifact, data=data), PruningPolicy())
    index = ObservationIndexCompiler().compile(manifest, (view,))
    return store, manifest, view, index, ObservationInspector(store, manifest)


def _named(snapshot: AxSnapshot, role: str) -> list[AxNode]:
    return [node for node in snapshot.nodes if node.role == role]


def test_frozen_artifacts_match_manifest_digests() -> None:
    for name, digest in MANIFEST['artifacts'].items():
        assert hashlib.sha256((ARTIFACTS / name).read_bytes()).hexdigest() == digest


def test_every_required_aria_pattern_survives_into_canonical_evidence() -> None:
    roles = {node.role for node in _snapshot().nodes}
    missing = [role for role in GROUND_TRUTH['widgets']['roles'] if role not in roles]
    assert not missing, f'AX artifact lost these ARIA patterns: {missing}'


def test_repeated_controls_differing_only_in_state_are_counted_not_flattened() -> None:
    """The threat, stated positively: state must survive a collapse that shape justified."""
    snapshot = _snapshot()
    expected = GROUND_TRUTH['channels']
    checkboxes = _named(snapshot, 'checkbox')
    states = [{prop.name: prop.value for prop in box.properties} for box in checkboxes]

    assert len(checkboxes) == expected['checkbox_count']
    assert sum(state.get('checked') == 'true' for state in states) == expected['checked_count']
    assert sum(state.get('disabled') == 'true' for state in states) == expected['disabled_count']


def test_the_checkbox_run_collapses_to_one_region_that_still_reports_its_states() -> None:
    _, _, view, _, _ = _bound()
    region = next(
        fragment
        for fragment in view.fragments
        if fragment.coverage is not None and 'Email' in fragment.summary and 'SMS' in fragment.summary
    )

    # Five wrappers of identical shape become one region plus one exemplar…
    assert region.coverage is not None
    assert region.coverage.observed == 5
    # …and the difference the shape deliberately ignored is stated in the summary.
    assert 'checked=true×2' in region.summary
    assert 'checked=false×3' in region.summary


def test_a_collapsed_region_expands_back_to_individually_addressable_members() -> None:
    _, _, view, _, inspector = _bound()
    region = next(
        fragment for fragment in view.fragments if fragment.coverage is not None and 'Production' in fragment.summary
    )
    page = inspector.expand(region.ref, InspectionBudget())

    assert [member.label for member in page.members] == [
        'tab "Production"',
        'tab "Staging"',
        'tab "Development"',
    ]
    assert all(member.stable for member in page.members)
    detail = AxNode.model_validate_json(inspector.inspect(page.members[1].ref, InspectionBudget()).content)
    assert detail.role == 'tab'
    assert ('selected', 'false') in [(prop.name, prop.value) for prop in detail.properties]


def test_ax_only_semantics_are_present_and_addressable() -> None:
    """Facts the accessibility tree computes that the DOM only implies."""
    snapshot = _snapshot()
    expected = GROUND_TRUTH['ax_only_semantics']
    by_state = {
        (node.role, ' '.join(node.name.split())): {prop.name: prop.value for prop in node.properties}
        for node in snapshot.nodes
    }

    assert by_state[('tab', expected['selected_tab'])]['selected'] == 'true'
    assert by_state[('option', expected['selected_option'])]['selected'] == 'true'
    assert by_state[('dialog', 'Confirm rollout')]['modal'] == 'true'
    assert by_state[('status', '')]['live'] == expected['live_politeness']
    assert by_state[('treeitem', expected['expanded_treeitem'])]['expanded'] == 'true'


def test_relationships_are_edges_and_reach_across_the_hierarchy() -> None:
    snapshot = _snapshot()
    by_id = snapshot.by_id
    dialog = next(node for node in snapshot.nodes if node.role == 'dialog')
    kinds = {relation.kind.value: relation for relation in dialog.relations}

    # The dialog's label lives in a heading that is its own child, and its description in a
    # sibling paragraph. Both are edges; neither was flattened into `child_ids`.
    assert 'labelledby' in kinds
    assert 'describedby' in kinds
    labelled_by = by_id[kinds['labelledby'].target_node_id or '']
    assert 'Confirm rollout' in ax_subtree_text(labelled_by, by_id)
    tab = next(node for node in snapshot.nodes if node.role == 'tab' and node.name == 'Production')
    controls = next(relation for relation in tab.relations if relation.kind.value == 'controls')
    assert by_id[controls.target_node_id or ''].role == 'tabpanel'


def test_the_dom_visible_defect_is_absent_from_ax_and_the_absence_is_explained() -> None:
    """The paired defect: a real button the accessibility tree does not have.

    This is the boss fight's central claim. The control is present, visible, and clickable in the
    rendered DOM; in AX only an ignored node and the browser's reason for ignoring it remain, and
    the accessible name is gone entirely. A reader must be able to see that something was excluded
    rather than conclude the page has nothing there.
    """
    expected = GROUND_TRUTH['defect_dom_only']
    _, _, view, index, _ = _bound()

    assert expected['dom_text'] in DOM_BYTES.decode()
    assert expected['dom_text'] not in AX_BYTES.decode()

    reasons = {reason.name for node in _snapshot().nodes for reason in node.ignored_reasons}
    assert expected['ax_ignored_reason'] in reasons
    assert expected['ax_subtree_reason'] in reasons

    # And it is discoverable from the index itself, not only from the raw artifact.
    stated = [entry for entry in index.entries if expected['ax_ignored_reason'] in entry.summary]
    assert stated, 'the index never mentions that a node was hidden from assistive technology'

    # The capability record, not a comment, is what tells a consumer how far to trust the absence.
    coverage = next(
        capability
        for capability in _snapshot().capabilities
        if capability.kind is AxCapabilityKind.VISIBLE_TEXT_COVERAGE
    )
    assert coverage.available is False
    assert coverage.reason
    assert 'AX absence is never proof' in view.fragments[0].summary


def test_the_ax_obvious_defect_is_reported_as_a_nameless_control() -> None:
    """The other half of the pair: obvious in AX, awkward to infer from DOM."""
    snapshot = _snapshot()
    nameless = [node for node in snapshot.nodes if node.role == 'button' and not node.name.strip()]
    assert len(nameless) == GROUND_TRUTH['defect_ax_only']['nameless_button_count']

    _, _, view, _, inspector = _bound()
    # The index names them by role alone — which is the finding — rather than borrowing a name
    # from their markup that no assistive technology would ever announce. Being identical in
    # shape AND nameless, the pair collapses into one region, so the finding reads "two buttons,
    # neither of which has a name".
    region = next(
        fragment for fragment in view.fragments if fragment.coverage is not None and fragment.label.endswith('> button')
    )
    assert region.coverage is not None
    assert region.coverage.observed == GROUND_TRUTH['defect_ax_only']['nameless_button_count']
    members = inspector.expand(region.ref, InspectionBudget()).members
    assert [member.label for member in members] == ['button', 'button']
    # No durable key exists for a control the page never named, and the index says so rather
    # than inventing one.
    assert 'some members are positional' in region.summary
    assert not any(member.stable for member in members)


def test_dom_correlation_is_declared_unavailable_rather_than_silently_omitted() -> None:
    correlation = next(
        capability for capability in _snapshot().capabilities if capability.kind is AxCapabilityKind.DOM_CORRELATION
    )
    assert correlation.available is False
    assert 'backendDOMNodeId' in (correlation.reason or '')
    # The join key itself is captured, so the gap is in the DOM artifact's addressing, not here.
    assert any(node.backend_dom_node_id is not None for node in _snapshot().nodes)
    assert (correlation.reason or '') in _bound()[2].fragments[0].summary


def test_the_same_capture_reduces_byte_identically() -> None:
    first = _bound()[2]
    second = _bound()[2]
    assert first.model_dump_json() == second.model_dump_json()
    assert first.policy_hash == second.policy_hash


def test_two_captures_of_the_same_tree_mint_the_same_identities() -> None:
    _, _, _, first, _ = _bound('capture-one')
    _, _, _, second, _ = _bound('capture-two')

    assert {entry.ref for entry in first.entries}.isdisjoint({entry.ref for entry in second.entries})
    assert [entry.ref_id for entry in first.entries] == [entry.ref_id for entry in second.entries]
    identified = [entry for entry in first.entries if entry.ref_id is not None]
    assert len(identified) / len(first.entries) > 0.8


def test_every_emitted_reference_resolves_against_its_exact_snapshot() -> None:
    _, _, _, index, inspector = _bound()
    for entry in index.entries:
        address = parse_address(entry.ref.locator)
        if address.is_region:
            assert inspector.expand(entry.ref, InspectionBudget()).members
        else:
            assert inspector.inspect(entry.ref, InspectionBudget()).returned_bytes > 0


def test_a_foreign_reference_fails_closed() -> None:
    _, manifest, _, index, inspector = _bound()
    foreign = index.entries[1].ref.model_copy(update={'snapshot_id': 'some-other-capture'})
    with pytest.raises(ObservationAddressError):
        inspector.inspect(foreign, InspectionBudget())

    unknown = RegionRef(
        snapshot_id=manifest.snapshot_id,
        artifact_sha256=index.entries[0].ref.artifact_sha256,
        modality=EvidenceKind.AX_TREE,
        locator='/ax/node/no-such-node',
    )
    with pytest.raises(ObservationAddressError):
        inspector.inspect(unknown, InspectionBudget())


def test_the_whole_index_fits_the_declared_overview_budget() -> None:
    _, _, _, index, _ = _bound()
    rendered = ObservationIndexRenderer().render(
        index, RenderPolicy(tokenizer_id=CharacterEstimator().id, token_budget=MANIFEST['budget_tokens'])
    )
    assert rendered.truncated is False
    assert rendered.token_count <= MANIFEST['budget_tokens']
    # The hidden-control finding must be in the OVERVIEW, not merely somewhere in the index.
    assert GROUND_TRUTH['defect_dom_only']['ax_ignored_reason'] in rendered.text


def test_the_canonical_artifact_is_unchanged_by_pruning() -> None:
    store, manifest, _, _, _ = _bound()
    stored = store.read(manifest.artifacts[0])
    assert stored == AX_BYTES
    assert hashlib.sha256(stored).hexdigest() == MANIFEST['artifacts']['ax_tree.json']


def test_the_paired_dom_capture_still_holds_what_ax_lost() -> None:
    """Cross-modal: neither modality is authoritative, and the contradiction is visible."""
    dom_store = MemoryArtifactStore()
    dom_artifact = dom_store.put(
        snapshot_id='aria-widgets-dom', kind=EvidenceKind.RENDERED_DOM, media_type='application/json', data=DOM_BYTES
    )
    dom_view = DomPruner().prune(PruningInput(source=dom_artifact, data=DOM_BYTES), PruningPolicy())
    _, _, ax_view, _, _ = _bound()

    hidden = GROUND_TRUTH['defect_dom_only']['dom_text']
    assert any(hidden in fragment.summary for fragment in dom_view.fragments)
    assert not any(hidden in fragment.summary for fragment in ax_view.fragments)
    assert ref_id(EvidenceKind.AX_TREE, ax_view.fragments[0].ref.locator) != ref_id(
        EvidenceKind.RENDERED_DOM, dom_view.fragments[0].ref.locator
    )
