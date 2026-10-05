"""Compare public Rust Map `Ord` pairs with the typed Python SDK ordering."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import parity

MODEL_TARGETS = {
    "discovery_source": "DiscoverySource",
    "observation": "Observation",
    "omission_reason": "OmissionReason",
    "relationship": "Relationship",
}
RUST_TYPES = {
    "discovery_source": "DiscoverySource",
    "observation": "Observation",
    "omission_reason": "OmissionReason",
    "public_provider": "PublicProvider",
    "rejection": "Rejection",
    "relationship": "Relationship",
    "relationship_kind": "RelationshipKind",
}


def _python_value(kind: str, value: Any, map_sdk: Any) -> Any:
    if kind in MODEL_TARGETS:
        from pydantic import TypeAdapter

        return TypeAdapter(getattr(map_sdk, MODEL_TARGETS[kind])).validate_python(value)
    if kind == "public_provider":
        return map_sdk.PublicProvider(value)
    if kind in {"rejection", "relationship_kind"} and isinstance(value, str):
        from pydantic import TypeAdapter

        return TypeAdapter(getattr(map_sdk, RUST_TYPES[kind])).validate_python(value)
    raise TypeError(f"unsupported Python value for Map ordering kind {kind!r}")


def _serde_view(kind: str, value: Any, map_sdk: Any) -> Any:
    if kind in MODEL_TARGETS:
        result = value.model_dump(mode="json", by_alias=True)
        if kind == "discovery_source" and result.get("value") is None:
            result.pop("value", None)
        elif kind == "omission_reason" and result.get("value") is None:
            result.pop("value", None)
        elif kind == "observation":
            result["source"] = _serde_view("discovery_source", value.source, map_sdk)
        return result
    if kind == "public_provider":
        return value.value
    return value


def observe_fixture(fixture: dict[str, Any], map_sdk: Any) -> dict[str, Any]:
    kind = fixture["kind"]
    left = _python_value(kind, fixture["left"], map_sdk)
    right = _python_value(kind, fixture["right"], map_sdk)
    left_view = _serde_view(kind, left, map_sdk)
    right_view = _serde_view(kind, right, map_sdk)
    python_cmp = map_sdk.compare_values(kind, left, right)

    python_operators: dict[str, Any]
    if kind in MODEL_TARGETS or kind == "public_provider":
        python_operators = {
            "lt": left < right,
            "le": left <= right,
            "gt": left > right,
            "ge": left >= right,
            "eq": left == right,
        }
        expected_operators = {
            "lt": fixture["rust_cmp"] < 0,
            "le": fixture["rust_cmp"] <= 0,
            "gt": fixture["rust_cmp"] > 0,
            "ge": fixture["rust_cmp"] >= 0,
            "eq": fixture["rust_cmp"] == 0,
        }
    else:
        # Literal aliases stay strings, so their Rust order is exposed through
        # compare_values while their normal string equality remains intact.
        python_operators = {"eq": left == right}
        expected_operators = {"eq": fixture["rust_cmp"] == 0}

    typed_values_equal = left_view == fixture["left"] and right_view == fixture["right"]
    rust = {
        key: fixture[key]
        for key in (
            "left",
            "right",
            "expected_cmp",
            "rust_cmp",
            "rust_partial_cmp",
            "fixture_passed",
        )
    }
    python = {
        "left": left_view,
        "right": right_view,
        "cmp": python_cmp,
        "operators": python_operators,
    }
    return {
        "name": fixture["name"],
        "kind": kind,
        "rust": rust,
        "python": python,
        "typed_values_equal": typed_values_equal,
        "rustReceiver": {"self": fixture["left"]},
        "rustArguments": {"other": fixture["right"]},
        "pythonArguments": {"kind": kind, "left": left_view, "right": right_view},
        "operator_checks": {
            key: python_operators.get(key) is expected
            for key, expected in expected_operators.items()
        },
        "passed": (
            fixture["fixture_passed"]
            and fixture["expected_cmp"] == fixture["rust_cmp"]
            and fixture["rust_partial_cmp"] == fixture["rust_cmp"]
            and python_cmp == fixture["rust_cmp"]
            and all(
                python_operators.get(key) is expected
                for key, expected in expected_operators.items()
            )
            and typed_values_equal
        ),
        "rustSha256": parity.digest_json(
            {
                "left": fixture["left"],
                "right": fixture["right"],
                "cmp": fixture["rust_cmp"],
            }
        ),
        "pythonSha256": parity.digest_json(
            {"left": left_view, "right": right_view, "cmp": python_cmp}
        ),
    }


def argument_checks(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check Rust self/other operands against the Python left/right inputs."""
    checks = []
    for kind, rust_key, python_key in (
        ("receiver", "self", "left"),
        ("argument", "other", "right"),
    ):
        rust_field = "rustReceiver" if kind == "receiver" else "rustArguments"
        rust_values = [item[rust_field][rust_key] for item in selected]
        python_values = [item["pythonArguments"][python_key] for item in selected]
        checks.append(
            {
                "kind": kind,
                "key": rust_key,
                "rustSha256": parity.digest_json(rust_values),
                "pythonSha256": parity.digest_json(python_values),
                "equal": rust_values == python_values,
            }
        )
    rust_kinds = [item["kind"] for item in selected]
    python_kinds = [item["pythonArguments"].get("kind") for item in selected]
    checks.append(
        {
            "kind": "fixed",
            "key": "kind",
            "rustSha256": parity.digest_json(rust_kinds),
            "pythonSha256": parity.digest_json(python_kinds),
            "equal": rust_kinds == python_kinds,
        }
    )
    return checks


def comparison_passes(comparison: dict[str, Any]) -> bool:
    return bool(comparison["passed"])


def _ord_symbol(
    rust: dict[str, Any], rust_path: str, trait: str = "Ord"
) -> dict[str, Any]:
    for item in rust["items"]:
        if (
            item.get("rustPath") == rust_path
            and item.get("trait") == trait
            and item.get("kind") == "function"
        ):
            return item
    raise parity.ParityError(f"Rust reference has no Ord::cmp item for {rust_path}")


def _case_for_type(
    kind: str,
    selected: list[dict[str, Any]],
    symbol: dict[str, Any],
) -> dict[str, Any]:
    mapping_checks = argument_checks(selected)
    passed = all(comparison_passes(item) for item in selected) and all(
        item["equal"] for item in mapping_checks
    )
    return {
        "testId": "map-ordering:" + symbol["rustPath"],
        "rustPath": symbol["rustPath"],
        "symbolKey": symbol["symbolKey"],
        "pythonTarget": "yosoi.map.compare_values",
        "trait": symbol["trait"],
        "operation": "cmp" if symbol["trait"] == "Ord" else "partial_cmp",
        "outcome": "passed" if passed else "failed",
        "mappingChecks": mapping_checks,
        "comparisons": [
            {
                "name": item["name"],
                "rustSha256": item["rustSha256"],
                "pythonSha256": item["pythonSha256"],
                "equal": item["passed"],
            }
            for item in selected
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument("--python-root", type=Path, default=None)
    args = parser.parse_args()

    process = subprocess.run(
        [str(args.rust_executable.resolve())],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    fixtures = json.loads(process.stdout)
    rust = parity.load_rust_inventory(args.rust_reference)
    python = parity.introspect_python_package(python_root=args.python_root)
    map_sdk = importlib.import_module("yosoi.map")
    comparisons = [observe_fixture(fixture, map_sdk) for fixture in fixtures]

    cases = []
    for kind, type_name in RUST_TYPES.items():
        symbol = _ord_symbol(rust, f"yosoi::map::{type_name}::cmp")
        selected = [item for item in comparisons if item["kind"] == kind]
        if not selected:
            raise parity.ParityError(f"Rust fixture contains no {kind} order pairs")
        cases.append(_case_for_type(kind, selected, symbol))
        partial = _ord_symbol(
            rust, f"yosoi::map::{type_name}::partial_cmp", "PartialOrd"
        )
        cases.append(_case_for_type(kind, selected, partial))

    target = "yosoi.map.compare_values"
    if target not in python["targets"]:
        raise parity.ParityError(f"Python reference has no {target} target")
    outcome = (
        "passed"
        if all(item["passed"] for item in comparisons)
        and all(case["outcome"] == "passed" for case in cases)
        else "failed"
    )
    result = {
        "schemaVersion": 1,
        "kind": "yosoi-python-rust-conformance-results",
        "runId": str(uuid.uuid4()),
        "source": {
            key: rust[key]
            for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
        },
        "python": {
            key: python[key]
            for key in ("surfaceDigest", "implementationDigest", "runtime")
        },
        "cases": cases,
        "outcome": outcome,
        "fixtureExecutableSha256": parity.digest_bytes(
            args.rust_executable.read_bytes()
        ),
        "comparisons": comparisons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.output.with_name(args.output.stem + "-results.json")
    raw_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    evidence = {
        key: result[key]
        for key in ("schemaVersion", "runId", "outcome", "source", "python", "cases")
    }
    evidence.update(
        kind="yosoi-python-rust-conformance",
        executedAt=datetime.now(UTC).isoformat(),
        runner={"command": [sys.executable, *sys.argv]},
        resultArtifact={
            "path": raw_path.name,
            "sha256": parity.digest_bytes(raw_path.read_bytes()),
        },
    )
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    passed = sum(item["passed"] for item in comparisons)
    print(f"{outcome}: {passed}/{len(comparisons)} Rust Map ordering comparisons")
    return 0 if outcome == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
