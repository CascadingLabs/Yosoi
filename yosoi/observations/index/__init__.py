"""Compilation, addressing, inspection, rendering, and diffing for observation indexes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.observations.index.addressing import ObservationAddress as ObservationAddress
    from yosoi.observations.index.addressing import ObservationAddressError as ObservationAddressError
    from yosoi.observations.index.addressing import format_address as format_address
    from yosoi.observations.index.addressing import parse_address as parse_address
    from yosoi.observations.index.addressing import resolve_index_entry as resolve_index_entry
    from yosoi.observations.index.compiler import ObservationCompileError as ObservationCompileError
    from yosoi.observations.index.compiler import ObservationIndexCompiler as ObservationIndexCompiler
    from yosoi.observations.index.diff import ObservationDiff as ObservationDiff
    from yosoi.observations.index.diff import diff_indexes as diff_indexes
    from yosoi.observations.index.inspect import InspectionBudget as InspectionBudget
    from yosoi.observations.index.inspect import InspectionResult as InspectionResult
    from yosoi.observations.index.inspect import ObservationInspector as ObservationInspector
    from yosoi.observations.index.inspect import RegionMember as RegionMember
    from yosoi.observations.index.inspect import RegionPage as RegionPage
    from yosoi.observations.index.render import ObservationIndexRenderer as ObservationIndexRenderer
    from yosoi.observations.index.render import RenderPolicy as RenderPolicy

_LAZY = {
    'InspectionBudget': 'yosoi.observations.index.inspect',
    'InspectionResult': 'yosoi.observations.index.inspect',
    'ObservationAddress': 'yosoi.observations.index.addressing',
    'ObservationAddressError': 'yosoi.observations.index.addressing',
    'ObservationCompileError': 'yosoi.observations.index.compiler',
    'ObservationDiff': 'yosoi.observations.index.diff',
    'ObservationIndexCompiler': 'yosoi.observations.index.compiler',
    'ObservationIndexRenderer': 'yosoi.observations.index.render',
    'ObservationInspector': 'yosoi.observations.index.inspect',
    'RegionMember': 'yosoi.observations.index.inspect',
    'RegionPage': 'yosoi.observations.index.inspect',
    'RenderPolicy': 'yosoi.observations.index.render',
    'format_address': 'yosoi.observations.index.addressing',
    'parse_address': 'yosoi.observations.index.addressing',
    'diff_indexes': 'yosoi.observations.index.diff',
    'resolve_index_entry': 'yosoi.observations.index.addressing',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
