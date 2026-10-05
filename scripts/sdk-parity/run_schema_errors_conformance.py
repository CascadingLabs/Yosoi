"""Compare public Rust schema errors with the Python typed error views."""

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

PYTHON_TYPES = {
    "ContractSchemaError": "yosoi.contracts.ContractSchemaFailure",
    "ExtractionFailure": "yosoi.contracts.RuntimeExtractionFailure",
    "ValidationFailure": "yosoi.contracts.RuntimeValidationFailure",
}


def resolve_path(value: Any, path: str) -> Any:
    """Resolve dotted mapping paths and numeric sequence components."""
    current = value
    for component in path.split(".") if path else ():
        if isinstance(current, dict) and component in current:
            current = current[component]
        elif isinstance(current, (list, tuple)) and component.isdecimal():
            index = int(component)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def select_comparisons(entry: dict, comparisons: list[dict]) -> list[dict]:
    """Attribute only mapped error types and exact enum variants."""
    if entry.get("decision") != "mapped" or entry.get("trait"):
        return []
    if any(entry.get(field) for field in ("defaults", "units", "cardinality")):
        return []
    if entry.get("argumentMappings") and not entry.get("variantBinding"):
        return []

    parts = entry["rustPath"].split("::")
    for rust_type in PYTHON_TYPES:
        if parts[-1] == rust_type:
            return [item for item in comparisons if item["rustType"] == rust_type]
        if len(parts) > 1 and parts[-2] == rust_type:
            binding = entry.get("variantBinding")
            return [
                item
                for item in comparisons
                if item["rustType"] == rust_type
                and (
                    item["rust"].get(binding["discriminator"]) == binding["tag"]
                    if binding
                    else item["variant"] == parts[-1]
                )
                and (binding or item["variant"] == parts[-1])
            ]
    return []


def payload_checks(entry: dict, selected: list[dict]) -> list[dict]:
    """Check ledger argument mappings against typed, discriminator-gated data."""
    checks = []
    binding = entry.get("variantBinding")
    for mapping in entry.get("argumentMappings", []):
        rust_path = str(mapping["rustArgument"])
        python_path = mapping["pythonArgument"]
        rust_values = [
            resolve_path(item.get("arguments", {}), rust_path) for item in selected
        ]
        python_values = [resolve_path(item["python"], python_path) for item in selected]
        valid = binding is not None and all(
            item[side].get(binding["discriminator"]) == binding["tag"]
            for item in selected
            for side in ("rust", "python")
        )
        present = all(value is not None for value in rust_values + python_values)
        checks.append(
            {
                "kind": "argument",
                "key": rust_path,
                "pythonPath": python_path,
                "rustSha256": parity.digest_json(rust_values),
                "pythonSha256": parity.digest_json(python_values),
                "equal": valid and present and rust_values == python_values,
            }
        )
    return checks


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
    comparisons = []
    for fixture in fixtures:
        target = PYTHON_TYPES[fixture["rust_type"]]
        module, name = target.rsplit(".", 1)
        adapter = TypeAdapter(getattr(importlib.import_module(module), name))
        observed = adapter.dump_python(
            adapter.validate_python(fixture["value"]), mode="json", exclude_none=True
        )
        nested = fixture["rust_type"] != "ContractSchemaError"
        message_preserved = (
            observed.get("message") == fixture["message"] if nested else None
        )
        comparisons.append(
            {
                "rustType": fixture["rust_type"],
                "variant": fixture["variant"],
                "case": fixture["case"],
                "pythonTarget": target,
                "rust": fixture["value"],
                "python": observed,
                "arguments": fixture["arguments"],
                "message": fixture["message"],
                "messagePreserved": message_preserved,
                "sourceChain": fixture["source_chain"],
                "equal": observed == fixture["value"]
                and message_preserved is not False,
                "rustSha256": parity.digest_json(fixture["value"]),
                "pythonSha256": parity.digest_json(observed),
            }
        )

    rust = parity.load_rust_inventory(args.rust_reference)
    python = parity.introspect_python_package()
    cases = []
    for entry in parity.load_ledger(args.ledger)["entries"]:
        selected = select_comparisons(entry, comparisons)
        if not selected:
            continue
        mappings = payload_checks(entry, selected)
        passed = all(item["equal"] for item in selected) and all(
            check["equal"] for check in mappings
        )
        cases.append(
            {
                "testId": "schema-error-values:" + entry["rustPath"],
                "rustPath": entry["rustPath"],
                "symbolKey": entry["symbolKey"],
                "pythonTarget": entry["pythonTarget"],
                "outcome": "passed" if passed else "failed",
                "mappingChecks": mappings,
                "comparisons": [
                    {
                        "name": "::".join(
                            (item["rustType"], item["variant"], item["case"])
                        ),
                        **{
                            key: item[key]
                            for key in (
                                "rustSha256",
                                "pythonSha256",
                                "equal",
                                "messagePreserved",
                                "sourceChain",
                            )
                        },
                    }
                    for item in selected
                ],
            }
        )

    fixture_outcome = (
        "passed" if all(item["equal"] for item in comparisons) else "failed"
    )
    conformance_outcome = (
        "passed"
        if fixture_outcome == "passed"
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
        "outcome": conformance_outcome,
        "fixtureOutcome": fixture_outcome,
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
    print(
        f"{result['outcome']}: {sum(item['equal'] for item in comparisons)}"
        f"/{len(comparisons)} schema error fixtures"
    )
    return 0 if result["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
