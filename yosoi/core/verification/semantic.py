"""Type-aware semantic validation of extracted field values.

Structural verification (:class:`~yosoi.core.verification.verifier.SelectorVerifier`)
only confirms that a selector matches *something* in the page. That is necessary
but not sufficient: a selector for a numeric ``score`` field can match a whole
comment card and "verify" while extracting 2,800 characters of prose. The LLM
never learns it was wrong.

This module asks the harder, type-aware question — *does the extracted value
look like the kind of thing the contract field declares?* — and turns failures
into human-readable feedback the discovery loop can replay to the LLM so it can
correct the selector (see ``Pipeline._scrape_fresh`` and CAS-78).

The engine is intentionally generic: it interprets the small set of
:class:`~yosoi.types.registry.SemanticRule` *kinds* (numeric / url / text) and
knows nothing about the specific built-in ``ys.*`` types. Each type declares its
own rule next to its ``register_coercion`` call, so custom types validate for
free.

v1 scope notes:

* Rule-based; no LLM calls (a deliberate non-goal for v1).
* Only **present, non-empty** values are checked. A missing/None value is an
  absence (handled structurally elsewhere), not a wrong shape — flagging it here
  would trigger endless re-discovery of legitimately-optional fields.
* A plain ``score: int`` field with no declared rule still validates as numeric,
  inferred from its Python annotation.
"""

from __future__ import annotations

import re
import typing
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yosoi.types.registry import (
    KIND_NUMERIC,
    KIND_TEXT,
    KIND_URL,
    SemanticRule,
    semantic_rule_for,
)

if TYPE_CHECKING:
    from yosoi.models.contract import Contract

# Default ceiling for numeric fields inferred from an int/float annotation.
_DEFAULT_NUMERIC_MAX_CHARS = 50

_PREVIEW_CHARS = 160
_HAS_DIGIT_RE = re.compile(r'\d')


@dataclass(frozen=True)
class FieldSemanticIssue:
    """A field whose extracted value does not match its declared semantic type.

    Attributes:
        field: The (flat) contract field name.
        raw_value: The extracted value, stringified, for quoting back to the LLM.
        reason: Human-readable explanation of why the value looks wrong.

    """

    field: str
    raw_value: str
    reason: str

    def as_feedback(self) -> str:
        """Render a feedback line for the discovery retry prompt."""
        value = self.raw_value
        length = len(value)
        preview = value if length <= _PREVIEW_CHARS else value[:_PREVIEW_CHARS] + '…'
        return (
            f'Your selector for `{self.field}` {self.reason} '
            f'It extracted {length} characters: {preview!r}. '
            f'Pick a selector that targets only the `{self.field}` value — '
            f'if it lives in an attribute, use a CSS `::attr(name)` pseudo-element.'
        )


class SemanticValidator:
    """Generic, rule-driven sanity checks for extracted field values."""

    def validate(
        self,
        item: Mapping[str, object],
        field_rules: Mapping[str, SemanticRule],
    ) -> list[FieldSemanticIssue]:
        """Check one extracted item against per-field semantic rules.

        Args:
            item: Extracted field name -> raw value (one repeating item, or the
                single-item content map).
            field_rules: Field name -> :class:`SemanticRule`. Fields without a
                rule are not checked. Build with :func:`field_rules_for_contract`.

        Returns:
            A list of issues (empty when every present, ruled value is well-shaped).

        """
        issues: list[FieldSemanticIssue] = []
        for field, value in item.items():
            rule = field_rules.get(field)
            if rule is None:
                continue
            issue = self._check(field, value, rule, item)
            if issue is not None:
                issues.append(issue)
        return issues

    def _check(
        self,
        field: str,
        value: object,
        rule: SemanticRule,
        item: Mapping[str, object],
    ) -> FieldSemanticIssue | None:
        text = _to_text(value)
        if text is None or not text.strip():
            return None  # absence is not a wrong shape — see module docstring

        if rule.kind == KIND_NUMERIC:
            if not _HAS_DIGIT_RE.search(text):
                return FieldSemanticIssue(field, text, 'returned text with no number in it.')
            if rule.max_chars is not None and len(text) > rule.max_chars:
                return FieldSemanticIssue(field, text, 'returned a long block of text, not a number.')
            return None

        if rule.kind == KIND_URL:
            if not (text.startswith('/') or text.startswith('http')):
                return FieldSemanticIssue(field, text, 'returned a value that is not a URL or path.')
            if rule.max_chars is not None and len(text) > rule.max_chars:
                return FieldSemanticIssue(field, text, 'returned text that is too long to be a URL.')
            return None

        if rule.kind == KIND_TEXT:
            if rule.max_chars is not None and len(text) > rule.max_chars:
                return FieldSemanticIssue(field, text, 'returned a long block of text, not a concise value.')
            if rule.distinct:
                dup = _duplicate_of(field, text, item)
                if dup is not None:
                    return FieldSemanticIssue(field, text, f'returned the same value as field `{dup}`.')
            return None

        return None


def _to_text(value: object) -> str | None:
    """Reduce an extracted value to a single string for shape checks, or None to skip."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str):
                return entry
        return None  # list of dicts (related_content) — not shape-checkable here
    if isinstance(value, (int, float)):
        # Native scalars from a live JS eval (eval_js returns native CDP types — a
        # numeric script yields an int/float/bool, not a string). Stringify so the
        # numeric/url/text rule actually inspects them; otherwise a JS field's
        # native return bypassed the shape check entirely (CAS-104). CSS values are
        # always strings, so this branch is JS-only in practice.
        return str(value)
    return None


def _duplicate_of(field: str, text: str, item: Mapping[str, object]) -> str | None:
    """Return the name of another field with an identical non-empty value, if any."""
    normalized = text.strip()
    if not normalized:
        return None
    for other, other_value in item.items():
        if other == field:
            continue
        other_text = _to_text(other_value)
        if other_text is not None and other_text.strip() == normalized:
            return other
    return None


def _is_numeric_annotation(annotation: object) -> bool:
    """True when the annotation is (optionally) int/float, e.g. ``int | None``."""
    numeric = (int, float)
    if annotation in numeric:
        return True
    args = typing.get_args(annotation)
    return any(arg in numeric for arg in args)


def _rule_for(yosoi_type: str | None, annotation: object) -> SemanticRule | None:
    """Resolve a field's rule from its declared type, falling back to its annotation."""
    rule = semantic_rule_for(yosoi_type)
    if rule is not None:
        return rule
    # No declared semantic type — infer a numeric rule from an int/float field.
    if _is_numeric_annotation(annotation):
        return SemanticRule(kind=KIND_NUMERIC, max_chars=_DEFAULT_NUMERIC_MAX_CHARS)
    return None


def field_rules_for_contract(contract: type[Contract]) -> dict[str, SemanticRule]:
    """Build a {flat field name -> SemanticRule} map for a contract.

    Mirrors the flattening used by :meth:`Contract.field_descriptions` /
    :meth:`Contract.discovery_field_names`: nested ``Contract`` fields expand to
    ``{parent}_{child}`` keys. Fields with neither a declared semantic type nor a
    numeric annotation are omitted (not validated).
    """
    from yosoi.models.contract import Contract as _Contract

    rules: dict[str, SemanticRule] = {}

    def _add(name: str, fi: object) -> None:
        extra = getattr(fi, 'json_schema_extra', None)
        yosoi_type = extra.get('yosoi_type') if isinstance(extra, dict) else None
        yosoi_type = str(yosoi_type) if yosoi_type is not None else None
        rule = _rule_for(yosoi_type, getattr(fi, 'annotation', None))
        if rule is not None:
            rules[name] = rule

    for name, fi in contract.model_fields.items():
        ann = fi.annotation
        if isinstance(ann, type) and issubclass(ann, _Contract):
            for child_name, child_fi in ann.model_fields.items():
                _add(f'{name}_{child_name}', child_fi)
        else:
            _add(name, fi)
    return rules
