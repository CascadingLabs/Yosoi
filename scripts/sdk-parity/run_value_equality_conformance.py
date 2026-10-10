"""Compare public Rust ProjectedValue equality with the Python SDK helper.

Build the fixture with ``cargo build -p yosoi --example
python_value_equality_conformance`` and run this script with that executable
and a snapshot-verified Rust reference artifact.
"""

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

from pydantic import TypeAdapter

import parity

PYTHON_TARGETS = {
    "eq": "yosoi.outcomes.projected_values_equal",
    "ne": "yosoi.outcomes.projected_values_not_equal",
}


def resolve_path(value: Any, path: str) -> tuple[bool, Any]:
    """Resolve a dotted path and distinguish a missing field from JSON null."""
    current = value
    for component in path.split(".") if path else ():
        if isinstance(current, dict) and component in current:
            current = current[component]
        elif isinstance(current, (list, tuple)) and component.isdecimal():
            index = int(component)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def select_comparisons(entry: dict, comparisons: list[dict]) -> list[dict]:
    """Select only explicitly mapped ProjectedValue PartialEq methods."""
    if entry.get("decision") != "mapped" or entry.get("trait") != "PartialEq":
        return []
    parts = entry.get("rustPath", "").split("::")
    if len(parts) < 2 or parts[-2] != "ProjectedValue" or parts[-1] not in {"eq", "ne"}:
        return []
    operation = parts[-1]
    symbol_key = entry.get("symbolKey", "")
    receiver = entry.get("receiverMapping") or {}
    if (
        entry.get("pythonTarget") != PYTHON_TARGETS[operation]
        or not symbol_key.startswith(f"member:function:{entry['rustPath']}@")
        or "@trait:PartialEq@" not in symbol_key
        or receiver.get("rustArgument") != "self"
        or receiver.get("pythonArgument") != "left"
        or not any(
            mapping.get("rustArgument") == "other"
            and mapping.get("pythonArgument") == "right"
            for mapping in entry.get("argumentMappings", [])
        )
    ):
        return []
    return comparisons


def payload_checks(entry: dict, selected: list[dict]) -> list[dict]:
    """Prove each mapped Rust argument is present and equal in Python inputs."""
    checks = []
    mappings = []
    if entry.get("receiverMapping"):
        mappings.append(("receiver", entry["receiverMapping"]))
    mappings.extend(
        ("argument", mapping) for mapping in entry.get("argumentMappings", [])
    )
    for mapping_kind, mapping in mappings:
        rust_path = str(mapping["rustArgument"])
        python_path = mapping["pythonArgument"]
        rust_results = [
            resolve_path(
                item["rustReceiver"]
                if rust_path in item["rustReceiver"]
                else item["rustArguments"],
                rust_path,
            )
            for item in selected
        ]
        python_results = [
            resolve_path(item["pythonArguments"], python_path) for item in selected
        ]
        rust_values = [value for _, value in rust_results]
        python_values = [value for _, value in python_results]
        present = all(found for found, _ in rust_results + python_results)
        checks.append(
            {
                "kind": mapping_kind,
                "key": rust_path,
                "pythonPath": python_path,
                "rustSha256": parity.digest_json(rust_values),
                "pythonSha256": parity.digest_json(python_values),
                "equal": present and rust_values == python_values,
            }
        )
    return checks


def operation_passes(comparison: dict, operation: str) -> bool:
    """Check one equality trait result against Rust, fixtures, and Python."""
    if operation not in {"eq", "ne"}:
        return False
    rust = comparison["rust"]
    python = comparison["python"]
    expected = rust[f"expected_{operation}"]
    rust_value = rust[f"rust_{operation}"]
    helper_value = python[f"helper_{operation}"]
    json_operator = python[f"json_operator_{operation}"]
    return (
        rust_value is expected
        and helper_value is rust_value
        and rust["fixture_passed"]
        and comparison["typed_values_equal"]
        and (json_operator is None or json_operator is rust_value)
    )


def observe_fixture(
    fixture: dict, adapter: TypeAdapter, helpers: dict[str, Any]
) -> dict:
    left = adapter.validate_python(fixture["left"])
    right = adapter.validate_python(fixture["right"])
    left_view = adapter.dump_python(
        left, mode="json", exclude_none=fixture["left"]["kind"] != "json"
    )
    right_view = adapter.dump_python(
        right, mode="json", exclude_none=fixture["right"]["kind"] != "json"
    )
    helper_eq = helpers["eq"](left, right)
    helper_ne = helpers["ne"](left, right)
    json_pair = fixture["left"].get("kind") == fixture["right"].get("kind") == "json"
    json_operator_eq = (left == right) if json_pair else None
    json_operator_ne = (left != right) if json_pair else None
    typed_values_equal = left_view == fixture["left"] and right_view == fixture["right"]
    rust = {
        key: fixture[key]
        for key in (
            "left",
            "right",
            "expected_eq",
            "expected_ne",
            "rust_eq",
            "rust_ne",
            "fixture_passed",
        )
    }
    python = {
        "left": left_view,
        "right": right_view,
        "helper_eq": helper_eq,
        "helper_ne": helper_ne,
        "json_operator_eq": json_operator_eq,
        "json_operator_ne": json_operator_ne,
    }
    return {
        "name": fixture["name"],
        "rust": rust,
        "python": python,
        "typed_values_equal": typed_values_equal,
        "rustArguments": {"other": fixture["right"]},
        "rustReceiver": {"self": fixture["left"]},
        "pythonArguments": {"left": left_view, "right": right_view},
        "eqPassed": operation_passes(
            {
                "rust": rust,
                "python": python,
                "typed_values_equal": typed_values_equal,
            },
            "eq",
        ),
        "nePassed": operation_passes(
            {
                "rust": rust,
                "python": python,
                "typed_values_equal": typed_values_equal,
            },
            "ne",
        ),
        "equal": operation_passes(
            {
                "rust": rust,
                "python": python,
                "typed_values_equal": typed_values_equal,
            },
            "eq",
        )
        and operation_passes(
            {
                "rust": rust,
                "python": python,
                "typed_values_equal": typed_values_equal,
            },
            "ne",
        ),
        "rustSha256": parity.digest_json(
            {
                "left": fixture["left"],
                "right": fixture["right"],
                "eq": fixture["rust_eq"],
                "ne": fixture["rust_ne"],
            }
        ),
        "pythonSha256": parity.digest_json(
            {
                "left": left_view,
                "right": right_view,
                "eq": helper_eq,
                "ne": helper_ne,
            }
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    args = parser.parse_args()

    process = subprocess.run(
        [str(args.rust_executable.resolve())],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    fixtures = json.loads(process.stdout)
    outcomes = importlib.import_module("yosoi.outcomes")
    adapter = TypeAdapter(outcomes.ProjectedValue)
    helpers = {
        "eq": outcomes.projected_values_equal,
        "ne": outcomes.projected_values_not_equal,
    }
    comparisons = [observe_fixture(fixture, adapter, helpers) for fixture in fixtures]

    rust = parity.load_rust_inventory(args.rust_reference)
    python = parity.introspect_python_package()
    cases = []
    for entry in parity.load_ledger(args.ledger)["entries"]:
        selected = select_comparisons(entry, comparisons)
        if not selected:
            continue
        operation = entry["rustPath"].split("::")[-1]
        mapping_checks = payload_checks(entry, selected)
        passed = all(item[f"{operation}Passed"] for item in selected) and all(
            check["equal"] for check in mapping_checks
        )
        cases.append(
            {
                "testId": "projected-value-equality:" + entry["rustPath"],
                "rustPath": entry["rustPath"],
                "symbolKey": entry["symbolKey"],
                "pythonTarget": entry["pythonTarget"],
                "trait": entry["trait"],
                "operation": operation,
                "outcome": "passed" if passed else "failed",
                "mappingChecks": mapping_checks,
                "comparisons": [
                    {
                        "name": item["name"],
                        "rustSha256": item["rustSha256"],
                        "pythonSha256": item["pythonSha256"],
                        "equal": item[f"{operation}Passed"],
                    }
                    for item in selected
                ],
            }
        )

    outcome = (
        "passed"
        if all(item["equal"] for item in comparisons)
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
    passed = sum(item["equal"] for item in comparisons)
    print(f"{outcome}: {passed}/{len(comparisons)} projected value comparisons")
    return 0 if outcome == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
