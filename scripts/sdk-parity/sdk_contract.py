#!/usr/bin/env python3
"""Reviewed semantic parity contract for Yosoi's Python-facing Rust SDK."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONTRACT_KIND = "yosoi-scoped-python-sdk-contract"
REPORT_KIND = "yosoi-scoped-sdk-semantic-parity"
CRATE = "yosoi"
NAMESPACES = (
    "contracts",
    "documents",
    "locators",
    "map",
    "policy",
    "request",
    "search",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# These are compiler-generated or language-level mechanics whose behavior is
# covered as a Rust capability, rather than a Python name-for-name API.
STANDARD_TRAIT_MECHANICS: dict[str, tuple[str, str]] = {
    "Clone": (
        "Rust Clone is a value-copying protocol implemented by the source type.",
        "The Python SDK's explicit clone operations and value ownership preserve "
        "the documented copied value semantics.",
    ),
    "Copy": (
        "Rust Copy is an implicit bitwise-copy marker for eligible values.",
        "Python values are passed by object reference; this Rust marker adds no "
        "separate Python operation.",
    ),
    "Debug": (
        "Rust Debug provides a diagnostic representation.",
        "Python repr(value) is the corresponding diagnostic representation "
        "where the SDK exposes the value.",
    ),
    "Display": (
        "Rust Display provides a user-facing textual representation.",
        "Python str(value) is the corresponding user-facing textual "
        "representation where the SDK exposes the value.",
    ),
    "Default": (
        "Rust Default constructs the documented default value.",
        "Python constructors and explicit default factories provide the "
        "documented default value.",
    ),
    "Eq": (
        "Rust Eq marks equality as reflexive for a value type.",
        "Python equality uses the SDK's value equality behavior for the "
        "corresponding type.",
    ),
    "PartialEq": (
        "Rust PartialEq compares values according to the type's documented fields.",
        "Python == uses the SDK's value equality behavior for the corresponding type.",
    ),
    "Hash": (
        "Rust Hash supplies a hash consistent with the type's equality implementation.",
        "Python hash(value) is the equivalent only for Python types that "
        "expose hashing.",
    ),
    "Ord": (
        "Rust Ord supplies total ordering for the type.",
        "Python rich comparisons provide ordering where the SDK exposes it.",
    ),
    "PartialOrd": (
        "Rust PartialOrd supplies partial ordering for the type.",
        "Python rich comparisons provide ordering where the SDK exposes it.",
    ),
    "From": (
        "Rust From supplies an infallible conversion into a target type.",
        "The corresponding Python constructor or explicit conversion helper "
        "provides the supported conversion.",
    ),
    "Into": (
        "Rust Into supplies an infallible conversion from a source value.",
        "The corresponding Python constructor or explicit conversion helper "
        "provides the supported conversion.",
    ),
    "TryFrom": (
        "Rust TryFrom supplies a checked conversion with a typed failure.",
        "The corresponding Python try_new, validator, or constructor exposes "
        "checked conversion and its SDK error.",
    ),
    "TryInto": (
        "Rust TryInto supplies a checked conversion with a typed failure.",
        "The corresponding Python try_new, validator, or constructor exposes "
        "checked conversion and its SDK error.",
    ),
    "FromStr": (
        "Rust FromStr parses a textual value with a typed failure.",
        "The corresponding Python parser or checked constructor exposes the "
        "supported textual conversion.",
    ),
    "AsRef": (
        "Rust AsRef exposes a borrowed view of a value.",
        "Python read-only properties and owning wrapper views expose the "
        "supported value without a Rust borrow API.",
    ),
    "Borrow": (
        "Rust Borrow exposes a borrowed view used by generic Rust APIs.",
        "Python values are passed directly; no separate borrowing operation "
        "is part of the Python API.",
    ),
    "ToOwned": (
        "Rust ToOwned turns a borrowed view into an owned value.",
        "Python wrapper objects already own their retained native values.",
    ),
    "Error": (
        "Rust Error integrates an error type with Rust's error-reporting protocol.",
        "The Python exception hierarchy and structured error attributes "
        "expose the corresponding failure.",
    ),
    "Serialize": (
        "Rust Serialize is a format-neutral trait; this parity contract makes "
        "no format-neutral wire claim.",
        "Only Yosoi's explicitly supported JSON wire APIs are covered by "
        "run_serde_conformance.py.",
    ),
    "Deserialize": (
        "Rust Deserialize is a format-neutral trait; this parity contract "
        "makes no format-neutral wire claim.",
        "Only Yosoi's explicitly supported JSON wire APIs are covered by "
        "run_serde_conformance.py.",
    ),
    "IntoIterator": (
        "Rust IntoIterator supports Rust iteration syntax.",
        "Python iteration is provided only by types that expose the "
        "corresponding Python iteration protocol.",
    ),
    "Iterator": (
        "Rust Iterator is a stateful iteration protocol.",
        "Python iteration is provided only by types that expose the "
        "corresponding Python iteration protocol.",
    ),
    "Deref": (
        "Rust Deref provides transparent target access for Rust syntax.",
        "Python wrapper accessors expose the supported target explicitly.",
    ),
    "DerefMut": (
        "Rust DerefMut provides mutable target access for Rust syntax.",
        "Python wrapper methods and properties expose only documented "
        "mutation operations.",
    ),
    "Index": (
        "Rust Index supports indexed access syntax.",
        "Python indexed access is covered only where the corresponding type "
        "exposes it.",
    ),
    "IndexMut": (
        "Rust IndexMut supports mutable indexed access syntax.",
        "Python indexed mutation is covered only where the corresponding "
        "type exposes it.",
    ),
    "Add": (
        "Rust Add implements addition for a type.",
        "Python arithmetic is covered only where the corresponding type exposes it.",
    ),
    "Sub": (
        "Rust Sub implements subtraction for a type.",
        "Python arithmetic is covered only where the corresponding type exposes it.",
    ),
    "Mul": (
        "Rust Mul implements multiplication for a type.",
        "Python arithmetic is covered only where the corresponding type exposes it.",
    ),
    "Div": (
        "Rust Div implements division for a type.",
        "Python arithmetic is covered only where the corresponding type exposes it.",
    ),
    "Neg": (
        "Rust Neg implements negation for a type.",
        "Python arithmetic is covered only where the corresponding type exposes it.",
    ),
    "Send": (
        "Rust Send is a compile-time thread-transfer marker.",
        "Python free-threading and runtime behavior are validated by their "
        "dedicated runtime checks.",
    ),
    "Sync": (
        "Rust Sync is a compile-time shared-reference thread-safety marker.",
        "Python free-threading and runtime behavior are validated by their "
        "dedicated runtime checks.",
    ),
    "Sized": (
        "Rust Sized is a compile-time type-layout bound.",
        "Python does not expose this Rust type-layout bound as a Python API.",
    ),
}

REQUIRED_SUITES = (
    "run_conformance.py",
    "run_diagnostics_conformance.py",
    "run_schema_errors_conformance.py",
    "run_value_equality_conformance.py",
    "run_errors_conformance.py",
    "run_map_ordering_conformance.py",
    "run_serde_conformance.py",
    "run_document_errors_conformance.py",
    "run_webtarget_conformance.py",
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(item: dict[str, Any]) -> tuple[str, str, str | None]:
    return (item.get("rustPath", ""), item.get("kind", ""), item.get("trait"))


def _identity_id(item: dict[str, Any], occurrence: int = 1) -> str:
    path, kind, trait = _identity(item)
    return f"{path}|{kind}|trait:{trait or ''}|occurrence:{occurrence}"


def _root_names(items: list[dict[str, Any]]) -> set[str]:
    root_names: set[str] = set()
    for item in items:
        path = item.get("rustPath")
        if not isinstance(path, str):
            continue
        parts = path.split("::")
        if (
            len(parts) == 2
            and parts[0] == CRATE
            and item.get("surface") == "item"
            and item.get("kind") != "module"
        ):
            root_names.add(parts[1])
    return root_names


def _identified_items(items: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    groups: dict[tuple[str, str, str | None], list[dict[str, Any]]] = {}
    root_names = _root_names(items)
    for item in items:
        if _is_in_scope(item, root_names):
            groups.setdefault(_identity(item), []).append(item)
    identified: list[tuple[str, dict[str, Any]]] = []
    for _identity_key, group in groups.items():
        ordered = sorted(
            group,
            key=lambda item: (
                _digest_text(item.get("signature") or ""),
                item.get("symbolKey") or "",
            ),
        )
        identified.extend(
            (_identity_id(item, occurrence), item)
            for occurrence, item in enumerate(ordered, 1)
        )
    return identified


def _is_in_scope(item: dict[str, Any], root_names: set[str] | None = None) -> bool:
    """Select root API items/members and the seven public namespaces."""
    path = item.get("rustPath")
    if not isinstance(path, str):
        return False
    parts = path.split("::")
    if len(parts) < 2 or parts[0] != CRATE:
        return False
    second = parts[1]
    if second in NAMESPACES:
        return True
    if second == "prelude":
        return len(parts) == 2 and item.get("kind") == "module"
    if len(parts) == 2:
        return item.get("surface") == "item"
    return second in (root_names or set())


def _mechanic(item: dict[str, Any]) -> dict[str, str] | None:
    trait = item.get("trait")
    if item.get("surface") == "member" and trait in STANDARD_TRAIT_MECHANICS:
        rationale, capability = STANDARD_TRAIT_MECHANICS[trait]
        return {"rationale": rationale, "equivalentCapability": capability}
    if item.get("kind") == "proc_macro":
        return {
            "rationale": (
                "Rust derive syntax is a compiler-time authoring mechanism. "
                "The Python SDK "
                "uses the public Contract class and Field declarations; extraction and "
                "validation semantics remain Rust-owned."
            ),
            "equivalentCapability": (
                "Python subclasses of yosoi.Contract declare fields with yosoi.Field. "
                "This maps the supported contract capability, not Rust derive syntax."
            ),
        }
    if item.get("rustPath") == "yosoi::prelude":
        return {
            "rationale": (
                "The Rust prelude is an import convenience re-exporting SDK names."
            ),
            "equivalentCapability": (
                "The same Python API is available from the yosoi root and named Python "
                "namespaces; the Rust prelude creates no additional Python API."
            ),
        }
    return None


def _expected_classification(declaration: dict[str, Any]) -> str:
    if declaration.get("rustPath") == "yosoi::prelude":
        return "prelude-mechanic"
    if declaration.get("kind") == "proc_macro":
        return "proc-macro-mechanic"
    if (
        declaration.get("surface") == "member"
        and declaration.get("trait") in STANDARD_TRAIT_MECHANICS
    ):
        return "trait-mechanic"
    return "sdk"


def _scope_item_from_report(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbolKey": item.get("symbolKey"),
        "id": item.get("id"),
        "rustPath": item.get("rustPath"),
        "kind": item.get("kind"),
        "trait": item.get("trait"),
        "surface": item.get("surface"),
        "parentRustPath": item.get("parentRustPath"),
        "signature": item.get("signature", ""),
        "status": item.get("status"),
        "python": item.get("python"),
        "mapping": item.get("mapping"),
        "evidence": item.get("evidence", []),
    }


def _mapping_projection(mapping: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(mapping, dict):
        return None
    keys = (
        "decision",
        "pythonTarget",
        "semanticEquivalent",
        "variantBinding",
        "receiverMapping",
        "fixedArguments",
        "argumentMappings",
        "defaults",
        "units",
        "cardinality",
        "rationale",
        "review",
    )
    projection = {
        key: mapping.get(
            key,
            []
            if key in {"argumentMappings", "defaults", "units", "cardinality"}
            else None,
        )
        for key in keys
    }
    for key in ("mappingDirection", "outputBinding"):
        if mapping.get(key) is not None:
            projection[key] = mapping[key]
    return projection


def _ledger_signature_digest(entry: dict[str, Any]) -> str | None:
    value = entry.get("rustSignatureSha256")
    if isinstance(value, str) and SHA256_RE.fullmatch(value):
        return value
    symbol_key = entry.get("symbolKey")
    if isinstance(symbol_key, str):
        match = re.search(r"@signature:([0-9a-f]{64})", symbol_key)
        if match:
            return match.group(1)
    return None


def _ledger_kind(entry: dict[str, Any]) -> str | None:
    symbol_key = entry.get("symbolKey")
    if not isinstance(symbol_key, str):
        return None
    for prefix in ("page:", "member:"):
        if symbol_key.startswith(prefix):
            remainder = symbol_key[len(prefix) :]
            kind, separator, _rest = remainder.partition(":")
            return kind if separator else None
    return None


def _ledger_trait(entry: dict[str, Any]) -> str | None:
    symbol_key = entry.get("symbolKey")
    if isinstance(symbol_key, str):
        match = re.search(r"@trait:([^@]+)", symbol_key)
        if match:
            return match.group(1)
    value = entry.get("trait")
    return value if isinstance(value, str) else None


def build_contract(inventory_report: dict[str, Any]) -> dict[str, Any]:
    """Create an initial auditable snapshot from a current full parity report.

    Scope selection is explicit: Rust root items/members and the seven named
    public namespaces, with only the `prelude` module added as an import-mechanic
    record. It does not infer SDK scope from visibility or Python package names.
    """
    coverage = inventory_report.get("coverage") or {}
    python = inventory_report.get("python") or {}
    targets = python.get("targets") or {}
    raw_items = coverage.get("items") or []
    declarations: list[dict[str, Any]] = []
    scoped_report_items = [_scope_item_from_report(item) for item in raw_items]
    for item_id, item in _identified_items(scoped_report_items):
        raw_item = next(
            candidate
            for candidate in raw_items
            if candidate.get("rustPath") == item.get("rustPath")
            and candidate.get("kind") == item.get("kind")
            and candidate.get("trait") == item.get("trait")
            and candidate.get("symbolKey") == item.get("symbolKey")
        )
        mechanic = _mechanic(item)
        classification = "sdk"
        if mechanic is not None:
            classification = (
                "trait-mechanic"
                if item.get("surface") == "member"
                and item.get("trait") in STANDARD_TRAIT_MECHANICS
                else "prelude-mechanic"
                if item.get("rustPath") == "yosoi::prelude"
                else "proc-macro-mechanic"
            )
        mapping = raw_item.get("mapping") or {}
        py_item = raw_item.get("python") or {}
        python_target = mapping.get("pythonTarget") or py_item.get("target")
        target_record = targets.get(python_target) if python_target else None
        target_digest = (
            _digest_json(target_record) if target_record is not None else None
        )
        mapping_decision = mapping.get("decision")
        if mapping_decision not in {"mapped", "language-specific"}:
            mapping_decision = "missing"
        review = mapping.get("review")
        if isinstance(review, dict):
            review = {
                key: review.get(key)
                for key in (
                    "status",
                    "rationale",
                    "pythonEquivalent",
                    "reviewer",
                    "reviewedAt",
                )
                if review.get(key) is not None
            }
        declaration = {
            "id": item_id,
            "rustPath": item["rustPath"],
            "kind": item["kind"],
            "trait": item.get("trait"),
            "surface": item.get("surface"),
            "parentRustPath": item.get("parentRustPath"),
            "signatureSha256": _digest_text(item.get("signature") or ""),
            "baselineStatus": item.get("status") or "missing",
            "symbolKey": item.get("symbolKey"),
            "classification": classification,
            "mapping": {
                "decision": mapping_decision,
                "pythonTarget": python_target,
                "pythonTargetSha256": target_digest,
                "semanticEquivalent": mapping.get("semanticEquivalent"),
                "rationale": mapping.get("rationale"),
                "review": review,
                "ledgerMappingSha256": (
                    _digest_json(_mapping_projection(raw_item.get("mapping")))
                    if classification == "sdk" and raw_item.get("mapping") is not None
                    else None
                ),
            },
        }
        if mechanic is not None:
            declaration["mechanic"] = mechanic
        declarations.append(declaration)
    declarations.sort(key=lambda item: item["id"])
    if len({item["id"] for item in declarations}) != len(declarations):
        raise ValueError("inventory report has duplicate scoped Rust declarations")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": CONTRACT_KIND,
        "sourceSnapshot": {
            "revision": (inventory_report.get("source") or {}).get("revision"),
            "inventorySignature": (inventory_report.get("source") or {}).get(
                "inventorySignature"
            ),
        },
        "scope": {"crate": CRATE, "root": True, "namespaces": list(NAMESPACES)},
        "wireEvidence": {
            "format": "JSON",
            "runner": "run_serde_conformance.py",
            "rationale": (
                "Wire evidence is limited to explicitly supported Yosoi JSON APIs; "
                "this contract makes no arbitrary-format serializer claim."
            ),
        },
        "standardTraitMechanics": {
            name: {"rationale": pair[0], "equivalentCapability": pair[1]}
            for name, pair in sorted(STANDARD_TRAIT_MECHANICS.items())
        },
        "declarations": declarations,
    }


def _validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("SDK contract must be a JSON object")
    if (
        contract.get("schemaVersion") != SCHEMA_VERSION
        or contract.get("kind") != CONTRACT_KIND
    ):
        raise ValueError("unsupported SDK contract schema or kind")
    scope = contract.get("scope")
    if (
        not isinstance(scope, dict)
        or scope.get("crate") != CRATE
        or scope.get("root") is not True
    ):
        raise ValueError("SDK contract scope must include the yosoi crate root")
    if scope.get("namespaces") != list(NAMESPACES):
        raise ValueError(
            "SDK contract namespaces do not match the seven reviewed namespaces"
        )
    source_snapshot = contract.get("sourceSnapshot")
    if not isinstance(source_snapshot, dict):
        raise ValueError("SDK contract sourceSnapshot must be an object")
    for field in ("revision", "inventorySignature"):
        value = source_snapshot.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"invalid SDK contract sourceSnapshot {field}")
    if source_snapshot.get(
        "inventorySignature"
    ) is not None and not SHA256_RE.fullmatch(source_snapshot["inventorySignature"]):
        raise ValueError("invalid SDK contract inventory signature")
    traits = contract.get("standardTraitMechanics")
    if not isinstance(traits, dict) or not traits:
        raise ValueError(
            "SDK contract standardTraitMechanics must be a nonempty object"
        )
    for trait, mechanic in traits.items():
        if not isinstance(trait, str) or not trait:
            raise ValueError(
                "SDK contract trait mechanic names must be nonempty strings"
            )
        if not isinstance(mechanic, dict) or not all(
            isinstance(mechanic.get(name), str) and mechanic[name].strip()
            for name in ("rationale", "equivalentCapability")
        ):
            raise ValueError(f"invalid standard trait mechanic: {trait}")
    declarations = contract.get("declarations")
    if not isinstance(declarations, list):
        raise ValueError("SDK contract declarations must be an array")
    seen: set[str] = set()
    valid_classifications = {
        "sdk",
        "trait-mechanic",
        "proc-macro-mechanic",
        "prelude-mechanic",
    }
    root_names = _root_names(declarations)
    for declaration in declarations:
        if not isinstance(declaration, dict):
            raise ValueError("SDK contract declarations must be objects")
        required = (
            "id",
            "rustPath",
            "kind",
            "signatureSha256",
            "classification",
            "surface",
            "baselineStatus",
        )
        if any(
            not isinstance(declaration.get(name), str) or not declaration[name]
            for name in required
        ):
            raise ValueError(
                "SDK declaration lacks required identity or mapping fields"
            )
        if not isinstance(declaration.get("mapping"), dict):
            raise ValueError(
                "SDK declaration lacks required identity or mapping fields"
            )
        if declaration.get("surface") not in {"item", "member"}:
            raise ValueError(
                f"invalid Rust declaration surface for {declaration['id']}"
            )
        if declaration.get("trait") is not None and not isinstance(
            declaration["trait"], str
        ):
            raise ValueError(f"invalid Rust trait name for {declaration['id']}")
        if declaration.get("parentRustPath") is not None and not isinstance(
            declaration["parentRustPath"], str
        ):
            raise ValueError(f"invalid Rust parent path for {declaration['id']}")
        if declaration.get("symbolKey") is not None and not isinstance(
            declaration["symbolKey"], str
        ):
            raise ValueError(f"invalid Rust symbol key for {declaration['id']}")
        if declaration.get("baselineStatus") not in {
            "mapped",
            "verified",
            "stale",
            "missing",
            "language-specific",
        }:
            raise ValueError(f"invalid baseline status for {declaration['id']}")
        if declaration["id"] in seen:
            raise ValueError(f"duplicate SDK declaration id: {declaration['id']}")
        seen.add(declaration["id"])
        if not SHA256_RE.fullmatch(declaration["signatureSha256"]):
            raise ValueError(f"invalid signature SHA-256 for {declaration['id']}")
        if declaration["classification"] not in valid_classifications:
            raise ValueError(f"unsupported SDK classification for {declaration['id']}")
        if not _is_in_scope(declaration, root_names):
            raise ValueError(
                "declaration is outside the reviewed SDK scope: "
                f"{declaration['rustPath']}"
            )
        expected_classification = _expected_classification(declaration)
        if declaration["classification"] != expected_classification:
            raise ValueError(
                f"invalid classification for {declaration['id']}: "
                f"expected {expected_classification}"
            )
        mapping = declaration["mapping"]
        if not isinstance(mapping, dict) or mapping.get("decision") not in {
            "mapped",
            "language-specific",
            "missing",
        }:
            raise ValueError(f"invalid mapping decision for {declaration['id']}")
        target = mapping.get("pythonTarget")
        if target is not None and not isinstance(target, str):
            raise ValueError(f"invalid Python target for {declaration['id']}")
        if mapping.get("decision") == "mapped" and not target:
            raise ValueError(
                f"mapped SDK declaration has no Python target: {declaration['id']}"
            )
        for field in ("semanticEquivalent", "rationale"):
            value = mapping.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"invalid mapping {field} for {declaration['id']}")
        review = mapping.get("review")
        if review is not None and (
            not isinstance(review, dict)
            or review.get("status") not in {"proposed", "reviewed"}
            or not isinstance(review.get("rationale"), str)
            or not isinstance(review.get("pythonEquivalent"), str)
        ):
            raise ValueError(f"invalid mapping review for {declaration['id']}")
        target_digest = mapping.get("pythonTargetSha256")
        if target_digest is not None and (
            not isinstance(target_digest, str) or not SHA256_RE.fullmatch(target_digest)
        ):
            raise ValueError(f"invalid Python target digest for {declaration['id']}")
        mapping_digest = mapping.get("ledgerMappingSha256")
        if mapping_digest is not None and (
            not isinstance(mapping_digest, str)
            or not SHA256_RE.fullmatch(mapping_digest)
        ):
            raise ValueError(f"invalid ledger mapping digest for {declaration['id']}")
        if declaration["classification"] != "sdk":
            mechanic = declaration.get("mechanic")
            if not isinstance(mechanic, dict) or not all(
                isinstance(mechanic.get(name), str) and mechanic[name].strip()
                for name in ("rationale", "equivalentCapability")
            ):
                raise ValueError(
                    f"reviewed mechanic rationale is missing for {declaration['id']}"
                )
    wire = contract.get("wireEvidence") or {}
    if (
        not isinstance(wire, dict)
        or wire.get("format") != "JSON"
        or wire.get("runner") != "run_serde_conformance.py"
        or not isinstance(wire.get("rationale"), str)
        or not wire["rationale"].strip()
    ):
        raise ValueError("SDK wire evidence must be limited to the JSON serde runner")
    return contract


def load_contract(path: Path | str) -> dict[str, Any]:
    """Load a contract and reject unsupported, malformed, or out-of-scope data."""
    try:
        contract = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read SDK contract {path}: {error}") from error
    return _validate_contract(contract)


def _inventory_items(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(inventory.get("items"), list):
        return inventory["items"]
    return list((inventory.get("coverage") or {}).get("items") or [])


def _pin_ledger(
    ledger: dict[str, Any], rust: dict[str, Any], python: dict[str, Any]
) -> None:
    ledger["sourcePin"] = {
        "sourceRevision": rust.get("sourceRevision"),
        "inventorySignature": rust.get("inventorySignature"),
        "featureProfileDigest": rust.get("featureProfileDigest"),
    }
    ledger["pythonPin"] = {
        "surfaceDigest": python.get("surfaceDigest"),
        "implementationDigest": python.get("implementationDigest"),
    }


def prepare_ledger(
    contract: dict[str, Any],
    rust: dict[str, Any],
    python: dict[str, Any],
    ledger: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return an ephemeral ledger rebased only after scoped structure matches.

    This function never writes. It allows source revisions, rustdoc inventory
    digests, Python implementation digests, and native binary bytes to change
    only when the reviewed Rust declarations and mapped Python target shapes
    remain structurally identical. Evidence freshness remains a separate gate.
    """
    _validate_contract(contract)
    fresh = copy.deepcopy(ledger)
    expected_by_id = {item["id"]: item for item in contract["declarations"]}
    current_by_id = dict(_identified_items(_inventory_items(rust)))
    drift: list[dict[str, Any]] = []
    for contract_id, expected in expected_by_id.items():
        current = current_by_id.get(contract_id)
        if current is None:
            drift.append(
                {
                    "kind": "rust-declaration-removed",
                    "id": contract_id,
                    "rustPath": expected["rustPath"],
                }
            )
            continue
        actual_signature = _digest_text(current.get("signature") or "")
        if actual_signature != expected["signatureSha256"]:
            drift.append(
                {
                    "kind": "rust-signature-changed",
                    "id": contract_id,
                    "rustPath": expected["rustPath"],
                    "expectedSha256": expected["signatureSha256"],
                    "actualSha256": actual_signature,
                }
            )
    for contract_id, current in current_by_id.items():
        if contract_id not in expected_by_id:
            drift.append(
                {
                    "kind": "rust-declaration-added",
                    "id": contract_id,
                    "rustPath": current.get("rustPath"),
                }
            )

    targets = python.get("targets") or {}
    for expected in contract["declarations"]:
        mapping = expected["mapping"]
        target = mapping.get("pythonTarget")
        expected_digest = mapping.get("pythonTargetSha256")
        if not target:
            continue
        if expected_digest is None:
            drift.append(
                {
                    "kind": "python-target-unsnapshotted",
                    "id": expected["id"],
                    "rustPath": expected["rustPath"],
                    "pythonTarget": target,
                }
            )
            continue
        actual_target = targets.get(target)
        if actual_target is None:
            drift.append(
                {
                    "kind": "python-target-removed",
                    "id": expected["id"],
                    "rustPath": expected["rustPath"],
                    "pythonTarget": target,
                }
            )
            continue
        actual_digest = _digest_json(actual_target)
        if actual_digest != expected_digest:
            drift.append(
                {
                    "kind": "python-target-changed",
                    "id": expected["id"],
                    "rustPath": expected["rustPath"],
                    "pythonTarget": target,
                    "expectedSha256": expected_digest,
                    "actualSha256": actual_digest,
                }
            )

    ledger_entries = fresh.get("entries", [])
    for expected in contract["declarations"]:
        expected_digest = expected["mapping"].get("ledgerMappingSha256")
        if expected_digest is None:
            continue
        expected_key = expected.get("symbolKey")
        candidates = [
            entry
            for entry in ledger_entries
            if expected_key is not None and entry.get("symbolKey") == expected_key
        ]
        if not candidates:
            candidates = [
                entry
                for entry in ledger_entries
                if entry.get("rustPath") == expected["rustPath"]
                if _ledger_trait(entry) == expected.get("trait")
            ]
        kind = _ledger_kind({"symbolKey": expected.get("symbolKey")})
        if kind is not None:
            candidates = [entry for entry in candidates if _ledger_kind(entry) == kind]
        signature_digest = expected["signatureSha256"]
        ledger_signatures = [_ledger_signature_digest(entry) for entry in candidates]
        if any(value is not None for value in ledger_signatures):
            candidates = [
                entry
                for entry in candidates
                if _ledger_signature_digest(entry) == signature_digest
            ]
        if len(candidates) != 1:
            drift.append(
                {
                    "kind": "ledger-mapping-removed",
                    "id": expected["id"],
                    "rustPath": expected["rustPath"],
                }
            )
            continue
        actual_digest = _digest_json(_mapping_projection(candidates[0]))
        if actual_digest != expected_digest:
            drift.append(
                {
                    "kind": "ledger-mapping-changed",
                    "id": expected["id"],
                    "rustPath": expected["rustPath"],
                    "expectedSha256": expected_digest,
                    "actualSha256": actual_digest,
                }
            )

    # Rebase symbol keys only if every reviewed Rust and Python shape still
    # matches. In particular, never rewrite signatures or mapping decisions.
    if not drift:
        current_by_path_trait: dict[
            tuple[str, str | None], list[tuple[str, dict[str, Any]]]
        ] = {}
        for item_id, item in current_by_id.items():
            current_by_path_trait.setdefault(
                (item.get("rustPath", ""), item.get("trait")), []
            ).append((item_id, item))
        for entry in fresh.get("entries", []):
            exact_current = next(
                (
                    item
                    for item in current_by_id.values()
                    if item.get("symbolKey") == entry.get("symbolKey")
                ),
                None,
            )
            if exact_current is not None:
                # Preserve a reviewed literal selector when it still resolves.
                continue
            trait_selector = _ledger_trait(entry)
            candidates = (
                current_by_path_trait.get((entry.get("rustPath", ""), trait_selector))
                or []
            )
            kind = _ledger_kind(entry)
            if kind is not None:
                candidates = [
                    pair for pair in candidates if pair[1].get("kind") == kind
                ]
            signature_digest = _ledger_signature_digest(entry)
            candidates = [
                (item_id, item)
                for item_id, item in candidates
                if item_id in expected_by_id
                and expected_by_id[item_id]["signatureSha256"]
                == _digest_text(item.get("signature") or "")
                and (
                    signature_digest is None
                    or _digest_text(item.get("signature") or "") == signature_digest
                )
            ]
            if len(candidates) == 1 and isinstance(
                candidates[0][1].get("symbolKey"), str
            ):
                entry["symbolKey"] = candidates[0][1]["symbolKey"]
    _pin_ledger(fresh, rust, python)
    return fresh, drift


def _case_comparisons(document: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for case in (
        document.get("cases", []) if isinstance(document.get("cases"), list) else []
    ):
        if isinstance(case, dict) and isinstance(case.get("comparisons"), list):
            comparisons.extend(
                item for item in case["comparisons"] if isinstance(item, dict)
            )
    # Some runner evidence carries aggregate comparisons beside case rows. They
    # remain valid capability observations only when the loader has validated it.
    aggregate = document.get("comparisons")
    if isinstance(aggregate, list):
        comparisons.extend(item for item in aggregate if isinstance(item, dict))
    return comparisons


def _suite_for_document(document: dict[str, Any]) -> str | None:
    runner = document.get("runner") or {}
    command = runner.get("command") if isinstance(runner, dict) else None
    if not isinstance(command, list):
        command = document.get("runnerCommand")
    if not isinstance(command, list):
        return None
    for part in command:
        if not isinstance(part, str):
            continue
        for suite in REQUIRED_SUITES:
            if part.endswith(suite):
                return suite
    return None


def _fresh_document(document: dict[str, Any]) -> bool:
    for name in (
        "sourceSnapshotMatches",
        "runtimeSnapshotMatches",
        "nativeSnapshotMatches",
    ):
        if name in document and document[name] is not True:
            return False
    matches = document.get("snapshotMatches")
    if isinstance(matches, dict) and (
        not matches or not all(value is True for value in matches.values())
    ):
        return False
    if document.get("snapshotMatchesAll") is True:
        return True
    return (
        isinstance(matches, dict)
        and bool(matches)
        and all(value is True for value in matches.values())
    )


def evaluate_contract(
    contract: dict[str, Any],
    rust: dict[str, Any],
    python: dict[str, Any],
    inventory_report: dict[str, Any],
    evidence_documents: list[dict[str, Any]],
    drift: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate mapping completeness, fresh suite capability, and item evidence."""
    _validate_contract(contract)
    report_items = _inventory_items(inventory_report)
    report_by_id = dict(_identified_items(report_items))
    sdk_declarations = [
        item for item in contract["declarations"] if item["classification"] == "sdk"
    ]
    missing_mappings: list[str] = []
    proposed_mappings: list[str] = []
    accepted_mappings: list[str] = []
    verified_items: list[str] = []
    mapped_unverified: list[str] = []
    item_status_counts: dict[str, int] = {}
    mapping_drift: list[dict[str, Any]] = []
    for declaration in sdk_declarations:
        mapping = declaration["mapping"]
        decision = mapping.get("decision")
        current = report_by_id.get(declaration["id"])
        current_status = current.get("status") if current else "missing"
        current_mapping = current.get("mapping") if current else None
        target = mapping.get("pythonTarget")
        target_digest = mapping.get("pythonTargetSha256")
        target_value = (python.get("targets") or {}).get(target) if target else None
        target_matches = target is None or (
            target_digest is not None
            and target_value is not None
            and _digest_json(target_value) == target_digest
        )
        if not target_matches:
            mapping_drift.append(
                {
                    "kind": "python-target-changed"
                    if target_value is not None
                    else "python-target-removed",
                    "id": declaration["id"],
                    "rustPath": declaration["rustPath"],
                    "pythonTarget": target,
                }
            )
        expected_mapping_digest = mapping.get("ledgerMappingSha256")
        if current and expected_mapping_digest is not None:
            actual_mapping_digest = _digest_json(_mapping_projection(current_mapping))
            if actual_mapping_digest != expected_mapping_digest:
                mapping_drift.append(
                    {
                        "kind": "report-mapping-changed",
                        "id": declaration["id"],
                        "rustPath": declaration["rustPath"],
                        "expectedSha256": expected_mapping_digest,
                        "actualSha256": actual_mapping_digest,
                    }
                )
        if decision == "mapped" and mapping.get("pythonTarget"):
            if (
                target_matches
                and current_status in {"mapped", "verified"}
                and isinstance(current_mapping, dict)
                and current_mapping.get("decision") == "mapped"
            ):
                accepted_mappings.append(declaration["id"])
            else:
                missing_mappings.append(declaration["id"])
        elif decision == "language-specific":
            review = mapping.get("review") or {}
            if (
                target_matches
                and current_status == "language-specific"
                and review.get("status") == "reviewed"
                and (
                    review.get("pythonEquivalent") or mapping.get("semanticEquivalent")
                )
            ):
                accepted_mappings.append(declaration["id"])
            else:
                if review.get("status") == "reviewed" and current_status in {
                    "missing",
                    "stale",
                    None,
                }:
                    missing_mappings.append(declaration["id"])
                else:
                    proposed_mappings.append(declaration["id"])
        else:
            missing_mappings.append(declaration["id"])
        status = current_status
        item_status_counts[status] = item_status_counts.get(status, 0) + 1
        if current and status == "verified" and current.get("evidence"):
            verified_items.append(declaration["id"])
        elif (
            decision in {"mapped", "language-specific"}
            and declaration["id"] in accepted_mappings
        ):
            mapped_unverified.append(declaration["id"])

    suites_by_name: dict[str, list[dict[str, Any]]] = {
        name: [] for name in REQUIRED_SUITES
    }
    unrecognized_evidence = 0
    for document in evidence_documents:
        if not isinstance(document, dict):
            unrecognized_evidence += 1
            continue
        suite = _suite_for_document(document)
        if suite is None:
            unrecognized_evidence += 1
            continue
        suites_by_name[suite].append(document)
    suite_rows: list[dict[str, Any]] = []
    missing_suites: list[str] = []
    stale_suites: list[str] = []
    failed_suites: list[str] = []
    for suite in REQUIRED_SUITES:
        documents = suites_by_name[suite]
        if not documents:
            missing_suites.append(suite)
            suite_rows.append({"name": suite, "status": "missing", "comparisons": 0})
            continue
        # Every supplied proof for a required suite must be current and passing.
        comparison_count = 0
        all_fresh = True
        all_passed = True
        all_have_comparisons = True
        for document in documents:
            outcome = document.get("outcome")
            comparisons = _case_comparisons(document)
            comparison_count += len(comparisons)
            doc_fresh = _fresh_document(document)
            all_fresh = all_fresh and doc_fresh
            all_passed = all_passed and outcome == "passed"
            all_have_comparisons = all_have_comparisons and bool(comparisons)
        if not all_fresh:
            stale_suites.append(suite)
            suite_status = "stale"
        elif not all_passed or not all_have_comparisons:
            failed_suites.append(suite)
            suite_status = "failed"
        else:
            suite_status = "passed"
        suite_rows.append(
            {
                "name": suite,
                "status": suite_status,
                "comparisons": comparison_count,
                "runs": len(documents),
            }
        )

    drift_rows = [copy.deepcopy(item) for item in (*drift, *mapping_drift)]
    for row in drift_rows:
        # Stable, user-readable descriptions are derived later by sdk_failures.
        row.setdefault("kind", "structural-drift")
    if drift_rows:
        parity_status = "stale"
    elif stale_suites:
        parity_status = "stale"
    elif missing_mappings or proposed_mappings or missing_suites or failed_suites:
        parity_status = "incomplete"
    else:
        parity_status = "complete"
    mapping_complete = not missing_mappings and not proposed_mappings
    behavior_passed = not missing_suites and not stale_suites and not failed_suites
    mechanism_counts: dict[str, int] = {}
    for declaration in contract["declarations"]:
        category = declaration["classification"]
        mechanism_counts[category] = mechanism_counts.get(category, 0) + 1
        if category == "trait-mechanic":
            trait = declaration.get("trait") or "<unknown>"
            mechanism_counts[f"trait:{trait}"] = (
                mechanism_counts.get(f"trait:{trait}", 0) + 1
            )
    counts = {
        "sdkDeclarations": len(sdk_declarations),
        "mapped": sum(
            1
            for item in sdk_declarations
            if item["id"] in accepted_mappings
            and item["mapping"].get("decision") == "mapped"
        ),
        "reviewedSemanticMappings": sum(
            1
            for item in sdk_declarations
            if item["id"] in accepted_mappings
            and item["mapping"].get("decision") == "language-specific"
        ),
        "proposedSemanticMappings": len(proposed_mappings),
        "missingMappings": len(missing_mappings),
        "mappedButUnverified": len(mapped_unverified),
        "individuallyVerified": len(verified_items),
        "rustMechanics": sum(
            1 for item in contract["declarations"] if item["classification"] != "sdk"
        ),
        "traitMechanics": mechanism_counts.get("trait-mechanic", 0),
        "preludeMechanics": mechanism_counts.get("prelude-mechanic", 0),
        "procMacroMechanics": mechanism_counts.get("proc-macro-mechanic", 0),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "generatedFrom": {
            "sourceRevision": rust.get("sourceRevision"),
            "inventorySignature": rust.get("inventorySignature"),
            "pythonSurfaceDigest": python.get("surfaceDigest"),
            "pythonImplementationDigest": python.get("implementationDigest"),
            "fixtureExecutables": copy.deepcopy(rust.get("fixtureExecutables") or {}),
        },
        "parityStatus": parity_status,
        "counts": counts,
        "mappingStatus": {
            "complete": mapping_complete,
            "mapped": counts["mapped"],
            "reviewedSemanticMappings": counts["reviewedSemanticMappings"],
            "proposedSemanticMappings": counts["proposedSemanticMappings"],
            "missing": counts["missingMappings"],
            "missingIds": missing_mappings,
            "proposedIds": proposed_mappings,
        },
        "behaviorStatus": {
            "passed": behavior_passed,
            "requiredSuites": list(REQUIRED_SUITES),
            "suites": suite_rows,
            "missingSuites": missing_suites,
            "staleSuites": stale_suites,
            "failedSuites": failed_suites,
            "unrecognizedEvidenceDocuments": unrecognized_evidence,
        },
        "structuralDrift": drift_rows,
        "individualItemEvidence": {
            "verified": len(verified_items),
            "mappedButUnverified": len(mapped_unverified),
            "statusCounts": item_status_counts,
            "verifiedIds": verified_items,
        },
        "mechanicCounts": mechanism_counts,
    }


def sdk_failures(sdk_report: dict[str, Any]) -> list[str]:
    """Return deterministic failures for the scoped SDK semantic-parity gate."""
    failures: list[str] = []
    status = sdk_report.get("parityStatus")
    if status == "stale":
        failures.append("scoped SDK contract or required evidence is stale")
    mapping = sdk_report.get("mappingStatus") or {}
    for item_id in mapping.get("missingIds") or []:
        failures.append(
            f"scoped SDK declaration has no Python semantic mapping: {item_id}"
        )
    for item_id in mapping.get("proposedIds") or []:
        failures.append(
            f"scoped SDK language-specific mapping is not reviewed: {item_id}"
        )
    for drift in sdk_report.get("structuralDrift") or []:
        path = (
            drift.get("rustPath")
            or drift.get("pythonTarget")
            or drift.get("id")
            or "unknown declaration"
        )
        failures.append(
            f"scoped SDK structural drift ({drift.get('kind', 'changed')}): {path}"
        )
    behavior = sdk_report.get("behaviorStatus") or {}
    for suite in behavior.get("missingSuites") or []:
        failures.append(f"required scoped SDK conformance suite is missing: {suite}")
    for suite in behavior.get("staleSuites") or []:
        failures.append(
            f"required scoped SDK conformance suite has stale proof: {suite}"
        )
    for suite in behavior.get("failedSuites") or []:
        failures.append(
            "required scoped SDK conformance suite failed or has no comparisons: "
            f"{suite}"
        )
    if status not in {"complete", "incomplete", "stale"}:
        failures.append("scoped SDK report has an invalid parityStatus")
    if status == "complete" and (
        mapping.get("complete") is not True
        or behavior.get("passed") is not True
        or sdk_report.get("structuralDrift")
    ):
        failures.append(
            "scoped SDK report claims complete while a required gate failed"
        )
    if status == "incomplete" and not failures:
        failures.append("scoped SDK parity report is incomplete")
    return failures
