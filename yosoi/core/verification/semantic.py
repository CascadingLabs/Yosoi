"""Semantic validation — does an extracted value actually look like the field it claims to be?

Sibling of :class:`SelectorVerifier` but at a different layer. The structural
verifier asks "does this selector match at least one element?" — a necessary
but not sufficient check. ``shreddit-post`` matches every post card on a
reddit listing, so it "verifies" — yet extracting through it returns 2 kB of
full-card text instead of the numeric ``score`` we asked for. The LLM never
sees the mismatch, so a one-shot pipeline has no way to self-correct.

This module closes that gap. After extraction, ``SemanticValidator.validate``
runs a per-field type-aware sanity check (dispatched off the Yosoi coercer
type on each contract field) and returns one ``FieldIssue`` per failing
field. The caller (``Pipeline._scrape_fresh``) feeds those issues back to
``FieldDiscoveryAgent.discover_field`` via a new ``feedback`` parameter,
re-discovers only the failing fields, re-extracts, and loops.

Checks are deliberately permissive: a false positive triggers an unnecessary
re-discovery (cheap), but a false negative cements bad data into the cache
(expensive). Rules of thumb:

  * Hard caps on length per semantic type (titles ≤ 500, scores ≤ 50, …) so
    a "whole card" extraction trips immediately.
  * Type-specific shape probes (URL-ish for ``url``; numeric for ``rating``).
  * Cross-field distinctness: if N>1 fields share the SAME extracted value,
    the LLM almost certainly latched onto the same wrong container for all
    of them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from yosoi.models.contract import Contract

# Per-type length caps. Tuned to flag "whole-card text" extractions on
# attribute-rich custom-element pages without false-positive on legitimate
# long titles / body text.
_MAX_LEN_BY_TYPE: dict[str | None, int] = {
    'title': 500,
    'author': 200,
    'url': 500,
    'price': 50,
    'rating': 50,
    'datetime': 100,
    'body_text': 50_000,  # bodies are legitimately long; cap protects against runaway extractions
    'related_content': 5_000,
    None: 500,  # the un-typed default (Field with no semantic type) — generous
}

# Minimum useful length: zero-length or single-char extractions are almost
# always upstream nulls leaking through coercion.
_MIN_LEN_BY_TYPE: dict[str | None, int] = {
    'body_text': 5,
    None: 1,
}


@dataclass(frozen=True)
class FieldIssue:
    """One field's failure. The ``reason`` text is fed back into the discovery agent.

    Attributes:
        field: Field name (matches the contract attribute).
        yosoi_type: The semantic type tag, e.g. ``'title'`` (``None`` if untyped).
        raw_value: The actual extracted value, truncated for logging/feedback.
        reason: One short sentence describing what failed. Surfaces to the LLM
            verbatim — should be specific enough that a corrective prompt
            ("you said `score` was at `shreddit-post`; it extracted 2,847 chars")
            can be assembled mechanically by the caller.
    """

    field: str
    yosoi_type: str | None
    raw_value: str | None
    reason: str


def _to_str(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        # Coercers may produce lists; join for sanity-check purposes only.
        return ' '.join(_to_str(item) or '' for item in v if item is not None)
    return str(v)


class SemanticValidator:
    """Run type-aware sanity checks against a single extracted record.

    Stateless. One instance per pipeline; ``validate(...)`` per record.
    """

    def __init__(self, contract: type[Contract]) -> None:
        """Stash the per-field yosoi-type map once so validate() is allocation-free."""
        self._contract = contract
        self._yosoi_types: dict[str, str | None] = _collect_yosoi_types(contract)

    def validate(self, record: Mapping[str, object]) -> list[FieldIssue]:
        """Return one FieldIssue per failing field. Empty list = clean pass.

        Only fields PRESENT in *record* (non-None) are validated — a field the
        extractor never produced is downstream pydantic's problem (the
        contract will surface a "field required" error there). The semantic
        validator's job is catching "extracted but wrong shape" failures the
        structural verifier accepts, not gating presence.

        Both per-field checks and cross-field distinctness run; issues from
        each are returned together so the caller can re-discover all failing
        fields in one round-trip.
        """
        issues: list[FieldIssue] = []
        for field, ytype in self._yosoi_types.items():
            if record.get(field) is None:
                continue
            raw = _to_str(record.get(field))
            issue = self._check_field(field, ytype, raw)
            if issue is not None:
                issues.append(issue)
        issues.extend(self._check_cross_field(record))
        # Dedupe — a field can fail both a per-field check and a cross-field
        # check; the per-field reason is the more actionable one.
        seen: set[str] = set()
        deduped: list[FieldIssue] = []
        for it in issues:
            if it.field in seen:
                continue
            seen.add(it.field)
            deduped.append(it)
        return deduped

    def _check_field(self, field: str, ytype: str | None, raw: str | None) -> FieldIssue | None:
        if raw is None or raw == '':
            min_len = _MIN_LEN_BY_TYPE.get(ytype, _MIN_LEN_BY_TYPE[None])
            if min_len > 0:
                return FieldIssue(field, ytype, raw, 'extracted value is empty or null')
            return None

        max_len = _MAX_LEN_BY_TYPE.get(ytype, _MAX_LEN_BY_TYPE[None])
        if len(raw) > max_len:
            preview = raw[:80].replace('\n', ' ')
            return FieldIssue(
                field,
                ytype,
                raw,
                f"extracted {len(raw):,} chars (max {max_len:,} for type '{ytype or 'text'}'); "
                f'likely matched a too-broad container. Preview: {preview!r}',
            )

        min_len = _MIN_LEN_BY_TYPE.get(ytype, _MIN_LEN_BY_TYPE[None])
        if len(raw) < min_len:
            return FieldIssue(
                field,
                ytype,
                raw,
                f'extracted {len(raw)} chars (min {min_len} for type {ytype!r}); likely an attribute-not-found null',
            )

        # Type-specific shape probes.
        if ytype in ('rating', 'price'):
            if not _looks_numeric(raw):
                return FieldIssue(
                    field,
                    ytype,
                    raw,
                    f"value {raw[:60]!r} does not look numeric for type '{ytype}'; "
                    f'selector likely matched a non-numeric element',
                )
        elif ytype == 'url':
            if not _looks_url_like(raw):
                return FieldIssue(
                    field,
                    ytype,
                    raw,
                    f"value {raw[:60]!r} does not look like a URL or path for type 'url'; "
                    f'selector likely matched anchor text instead of href',
                )
        elif ytype == 'datetime' and not _looks_datetime_like(raw):
            return FieldIssue(
                field,
                ytype,
                raw,
                f"value {raw[:60]!r} does not look like a date for type 'datetime'",
            )
        return None

    def _check_cross_field(self, record: Mapping[str, object]) -> list[FieldIssue]:
        """Flag collisions where multiple fields share an identical extracted value.

        When that happens the LLM almost always picked the same wrong container
        for every colliding field.
        """
        by_value: dict[str, list[str]] = {}
        for field in self._yosoi_types:
            raw = _to_str(record.get(field))
            if not raw or len(raw) < 3:
                continue
            by_value.setdefault(raw, []).append(field)
        issues: list[FieldIssue] = []
        for value, fields in by_value.items():
            if len(fields) < 2:
                continue
            others = ', '.join(repr(f) for f in fields if f != fields[0])
            issues.extend(
                FieldIssue(
                    f,
                    self._yosoi_types.get(f),
                    value,
                    f'extracted value equals other fields ({others}); '
                    f'selectors likely all matched the same wrong container',
                )
                for f in fields
            )
        return issues


def _looks_numeric(s: str) -> bool:
    """True if ``s`` contains a parseable number (commas/$/£/€ tolerated)."""
    cleaned = re.sub(r'[,$£€\s]', '', s.strip())
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        # Star ratings like "4.5 stars" — accept if a number sits at the front.
        m = re.match(r'^-?\d+(?:\.\d+)?', cleaned)
        return m is not None


def _looks_url_like(s: str) -> bool:
    """Permissive URL/path probe — anything an LLM might reasonably emit as a link."""
    stripped = s.strip()
    if not stripped:
        return False
    if stripped.startswith(('http://', 'https://', '//', '/')):
        return True
    if '://' in stripped:
        return True
    # Bare domain (example.com/path) is plausible; require a dot + no spaces.
    return '.' in stripped and ' ' not in stripped and len(stripped) < 500


def _looks_datetime_like(s: str) -> bool:
    """Permissive datetime probe — digits + a date-shaped separator or month word."""
    if not re.search(r'\d', s):
        return False
    return bool(re.search(r'[-:/T]|\d{4}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec', s, re.IGNORECASE))


def _collect_yosoi_types(contract: type[Contract]) -> dict[str, str | None]:
    """Map every (flattened) contract field to its ``yosoi_type`` tag, or None."""
    result: dict[str, str | None] = {}
    for name, fi in contract.model_fields.items():
        ann = fi.annotation
        if isinstance(ann, type) and issubclass(ann, Contract):
            for child_name, child_fi in ann.model_fields.items():
                result[f'{name}_{child_name}'] = _field_yosoi_type(child_fi)
        else:
            result[name] = _field_yosoi_type(fi)
    return result


def _field_yosoi_type(field_info: object) -> str | None:
    extra = getattr(field_info, 'json_schema_extra', None)
    if isinstance(extra, dict):
        ytype = extra.get('yosoi_type')
        if isinstance(ytype, str):
            return ytype
    return None


def render_feedback(
    issues: Iterable[FieldIssue], previous_selectors: Mapping[str, Mapping[str, object]]
) -> dict[str, str]:
    """Build a per-field feedback message keyed by field name.

    The message is what the discovery agent's prompt receives verbatim under
    "Previous attempt failed because:". It must be specific enough that the
    LLM can identify the mistake and pivot to ``attr`` / ``global_id`` /
    a tighter CSS selector.
    """
    msgs: dict[str, str] = {}
    for issue in issues:
        prev = previous_selectors.get(issue.field, {})
        # Surface the prior selector verbatim so the LLM can compare what it
        # picked against the failure mode.
        prev_repr = _format_prev_selector(prev)
        msgs[issue.field] = (
            f'Previous attempt for field {issue.field!r}: selector {prev_repr} '
            f'failed semantic validation. Reason: {issue.reason}. '
            f'Try a DIFFERENT selector this time — re-check the rubric, '
            f'especially RULE 1 if the value might live on the card itself.'
        )
    return msgs


def _format_prev_selector(prev: Mapping[str, object]) -> str:
    """Compact representation of the previous selector for the feedback prompt."""
    primary = prev.get('primary')
    if isinstance(primary, dict):
        return repr({k: v for k, v in primary.items() if k in ('type', 'value', 'identity')})
    if isinstance(primary, str):
        return repr(primary)
    return repr(dict(prev))
