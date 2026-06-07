"""A tiny stdio MCP server exposing Yosoi's SemanticValidator as a ``check_value`` tool.

This is the *one* shared mechanism that gives every MCP-discovery backend the same
in-loop self-correction. Whether discovery runs through pydantic-ai's own tool loop
(provider-API models) or through a subscription SDK's native loop (OpenCode, Claude
Agent SDK), each one mounts this server by command and the agent calls
``check_value(field, value)`` after extracting a value — before recording the
selector. Returning anything but ``"ok"`` tells the agent its selector grabbed the
wrong kind of thing, so it tries again against the live DOM.

The server is contract-agnostic on its own; the discovering process passes the
contract's per-field rules in via the ``YOSOI_FIELD_RULES`` environment variable as
JSON ``{field: {kind, max_chars?, distinct?}}`` (see :func:`field_rules_env`). A
field with no rule always validates ``"ok"`` — absence of a rule is not a failure.
"""

from __future__ import annotations

import json
import os

from yosoi.core.verification.semantic import SemanticValidator
from yosoi.types.registry import SemanticRule

#: Environment variable carrying the JSON-encoded per-field rules.
FIELD_RULES_ENV = 'YOSOI_FIELD_RULES'


def field_rules_env(field_rules: dict[str, SemanticRule]) -> str:
    """Serialise per-field rules for the ``YOSOI_FIELD_RULES`` env var.

    Args:
        field_rules: Field name -> :class:`SemanticRule`.

    Returns:
        JSON string the validator server reconstructs at startup.

    """
    payload = {
        name: {'kind': rule.kind, 'max_chars': rule.max_chars, 'distinct': rule.distinct}
        for name, rule in field_rules.items()
    }
    return json.dumps(payload)


def _load_rules() -> dict[str, SemanticRule]:
    raw = os.getenv(FIELD_RULES_ENV)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    rules: dict[str, SemanticRule] = {}
    for name, spec in data.items():
        if not isinstance(spec, dict) or 'kind' not in spec:
            continue
        rules[name] = SemanticRule(
            kind=str(spec['kind']),
            max_chars=spec.get('max_chars'),
            distinct=bool(spec.get('distinct', False)),
        )
    return rules


def _check_value_feedback(field: str, value: str, rules: dict[str, SemanticRule]) -> str:
    """Evaluate a single field value and return check feedback.

    This helper keeps rule checks available as a pure function for tests and
    mirrors the same semantics as the MCP-registered ``check_value`` tool.
    """
    validator = SemanticValidator()
    rule = rules.get(field)
    if rule is None:
        return 'ok'
    issues = validator.validate({field: value}, {field: rule})
    if not issues:
        return 'ok'
    return issues[0].as_feedback()


def build_server() -> object:
    """Construct the FastMCP server with the ``check_value`` tool registered."""
    from mcp.server.fastmcp import FastMCP

    rules = _load_rules()
    server = FastMCP('yosoi-validator')

    @server.tool()
    def check_value(field: str, value: str) -> str:
        """Check that an extracted value matches a contract field's semantic type.

        Call this after extracting a value, before recording the selector that
        produced it. Returns ``"ok"`` when the value is well-shaped (or the field
        has no rule), otherwise a short reason to try a different selector.
        """
        return _check_value_feedback(field, value, rules)

    return server


def main() -> None:
    """Console-script entry point: serve ``check_value`` over stdio."""
    server = build_server()
    server.run('stdio')  # type: ignore[attr-defined]


if __name__ == '__main__':
    main()
