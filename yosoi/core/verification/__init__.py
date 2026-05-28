"""Selector verification components.

Two complementary checks at different layers:

  * :class:`SelectorVerifier` (structural) — "does this selector match at
    least one element?" Necessary but not sufficient.
  * :class:`SemanticValidator` (type-aware) — "does the extracted value
    actually look like the field it claims to be?" Catches "selector matched
    too broadly" failures the structural check passes through.
"""

from yosoi.core.verification.semantic import FieldIssue, SemanticValidator, render_feedback
from yosoi.core.verification.verifier import SelectorVerifier

__all__ = ['FieldIssue', 'SelectorVerifier', 'SemanticValidator', 'render_feedback']
