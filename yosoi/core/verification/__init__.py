"""Selector verification components.

Lazy (PEP 562) so importing ``yosoi.core.verification.semantic`` (the only piece
the validator subprocess needs) does not also pull ``SelectorVerifier`` and its
parsing stack through this package ``__init__``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.core.verification.semantic import FieldSemanticIssue as FieldSemanticIssue
    from yosoi.core.verification.semantic import SemanticValidator as SemanticValidator
    from yosoi.core.verification.semantic import field_rules_for_contract as field_rules_for_contract
    from yosoi.core.verification.verifier import SelectorVerifier as SelectorVerifier

_LAZY: dict[str, str] = {
    'FieldSemanticIssue': 'yosoi.core.verification.semantic',
    'SemanticValidator': 'yosoi.core.verification.semantic',
    'field_rules_for_contract': 'yosoi.core.verification.semantic',
    'SelectorVerifier': 'yosoi.core.verification.verifier',
}

__all__ = ['FieldSemanticIssue', 'SelectorVerifier', 'SemanticValidator', 'field_rules_for_contract']


def __getattr__(name: str) -> object:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
