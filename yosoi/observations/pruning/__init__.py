"""Deterministic, modality-specific observation pruners."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.observations.pruning._base import PruneCandidate as PruneCandidate
    from yosoi.observations.pruning._base import Reduction as Reduction
    from yosoi.observations.pruning._base import SemanticPruner as SemanticPruner
    from yosoi.observations.pruning.ax import AxPruner as AxPruner
    from yosoi.observations.pruning.dom import DomPruner as DomPruner
    from yosoi.observations.pruning.html import BodyPruner as BodyPruner
    from yosoi.observations.pruning.html import DeclarationPruner as DeclarationPruner
    from yosoi.observations.pruning.network import NetworkPruner as NetworkPruner
    from yosoi.observations.pruning.protocol import Pruner as Pruner
    from yosoi.observations.pruning.protocol import PruningInput as PruningInput
    from yosoi.observations.pruning.protocol import PruningPolicy as PruningPolicy

_LAZY = {
    'AxPruner': 'yosoi.observations.pruning.ax',
    'DomPruner': 'yosoi.observations.pruning.dom',
    'BodyPruner': 'yosoi.observations.pruning.html',
    'DeclarationPruner': 'yosoi.observations.pruning.html',
    'PruneCandidate': 'yosoi.observations.pruning._base',
    'Reduction': 'yosoi.observations.pruning._base',
    'SemanticPruner': 'yosoi.observations.pruning._base',
    'NetworkPruner': 'yosoi.observations.pruning.network',
    'Pruner': 'yosoi.observations.pruning.protocol',
    'PruningInput': 'yosoi.observations.pruning.protocol',
    'PruningPolicy': 'yosoi.observations.pruning.protocol',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
