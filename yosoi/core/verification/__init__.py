"""Selector verification components.

Lazy (PEP 562) so importing ``yosoi.core.verification.semantic`` (the only piece
the validator subprocess needs) does not also pull ``SelectorVerifier`` and its
parsing stack through this package ``__init__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

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

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
