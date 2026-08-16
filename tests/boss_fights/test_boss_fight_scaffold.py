"""Structural proof that the boss-fight tier and modality scaffolds are present."""

from __future__ import annotations

from pathlib import Path

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.pruning import AxPruner, BodyPruner, DeclarationPruner, DomPruner, NetworkPruner

# A modality can have several pruners — source HTML has one for declarations and one for
# structure — so workload directories are keyed by evidence kind, not by pruner name.
DIRECTORY_BY_KIND = {
    EvidenceKind.SOURCE_HTML: 'html',
    EvidenceKind.RENDERED_DOM: 'dom',
    EvidenceKind.AX_TREE: 'ax',
    EvidenceKind.NETWORK: 'network',
}


def test_all_initial_pruning_modes_have_a_boss_fight_directory(boss_fights_root: Path) -> None:
    pruners = (DeclarationPruner(), BodyPruner(), DomPruner(), AxPruner(), NetworkPruner())

    assert {pruner.evidence_kind for pruner in pruners} == set(DIRECTORY_BY_KIND)
    assert all((boss_fights_root / DIRECTORY_BY_KIND[pruner.evidence_kind]).is_dir() for pruner in pruners)


def test_pruner_names_are_unique_across_modalities() -> None:
    pruners = (DeclarationPruner(), BodyPruner(), DomPruner(), AxPruner(), NetworkPruner())

    names = [pruner.name for pruner in pruners]
    assert len(names) == len(set(names))
