"""Structural proof that the boss-fight tier and modality scaffolds are present."""

from __future__ import annotations

from pathlib import Path

from yosoi.observations.pruning import AxPruner, DomPruner, HtmlPruner, NetworkPruner


def test_all_initial_pruning_modes_have_a_boss_fight_directory(boss_fights_root: Path) -> None:
    pruners = (HtmlPruner(), DomPruner(), AxPruner(), NetworkPruner())

    assert {pruner.name for pruner in pruners} == {'html', 'dom', 'ax', 'network'}
    assert all((boss_fights_root / pruner.name).is_dir() for pruner in pruners)
