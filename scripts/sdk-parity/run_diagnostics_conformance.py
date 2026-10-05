"""Compare every Rust SDK diagnostic fixture with its Python typed view."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

import parity

PYTHON_TYPES = {
    name: f"yosoi.diagnostics.{name}"
    for name in (
        "WebArtifactFamily",
        "UnknownReason",
        "DecodingErrorCode",
        "BrowserFailureReason",
        "DirectHttpRedirectErrorKind",
        "PartialReason",
        "UnavailableReason",
        "UnprojectableReason",
        "AttemptFailureKind",
        "NotStartedReason",
        "AttemptDiagnostic",
        "SearchAttemptDiagnostic",
    )
}
PYTHON_TYPES["DirectHttpTransportErrorKind"] = "yosoi.diagnostics.TransportDiagnostic"
PYTHON_TYPES["Rejection"] = "yosoi.map.Rejection"


def select_comparisons(entry: dict, comparisons: list[dict]) -> list[dict]:
    """Attribute only enum types and exact variants, never unrelated traits."""
    if entry.get("decision") != "mapped" or entry.get("trait"):
        return []
    if any(entry.get(field) for field in ("defaults", "units", "cardinality")):
        return []
    if entry.get("argumentMappings") and not entry.get("variantBinding"):
        return []
    parts = entry["rustPath"].split("::")
    for name in PYTHON_TYPES:
        if parts[-1] == name:
            return [item for item in comparisons if item["rustType"] == name]
        if len(parts) > 1 and parts[-2] == name:
            binding = entry.get("variantBinding")
            return [
                item
                for item in comparisons
                if item["rustType"] == name
                and (
                    isinstance(item["rust"], dict)
                    and item["rust"].get(binding["discriminator"]) == binding["tag"]
                    if binding
                    else item["variant"] == parts[-1]
                )
            ]
    return []


def payload_checks(entry: dict, selected: list[dict]) -> list[dict]:
    checks = []
    for mapping in entry.get("argumentMappings", []):
        key = mapping["pythonArgument"]
        binding = entry["variantBinding"]
        valid = all(
            isinstance(item[side], dict)
            and key in item[side]
            and item[side].get(binding["discriminator"]) == binding["tag"]
            for item in selected
            for side in ("rust", "python")
        )
        left = [item["rust"].get(key) for item in selected]
        right = [item["python"].get(key) for item in selected]
        checks.append(
            {
                "kind": "argument",
                "key": mapping["rustArgument"],
                "rustSha256": parity.digest_json(left),
                "pythonSha256": parity.digest_json(right),
                "equal": valid and left == right,
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
        if "message" in fixture:
            from yosoi.map import rejection_message

            observed = {"value": observed, "message": rejection_message(observed)}
            fixture = {
                **fixture,
                "value": {"value": fixture["value"], "message": fixture["message"]},
            }
        comparisons.append(
            {
                "rustType": fixture["rust_type"],
                "variant": fixture["variant"],
                "pythonTarget": target,
                "rust": fixture["value"],
                "python": observed,
                "equal": observed == fixture["value"],
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
        cases.append(
            {
                "testId": "diagnostic-values:" + entry["rustPath"],
                "rustPath": entry["rustPath"],
                "symbolKey": entry["symbolKey"],
                "pythonTarget": entry["pythonTarget"],
                "outcome": "passed"
                if all(item["equal"] for item in selected)
                else "failed",
                "mappingChecks": payload_checks(entry, selected),
                "comparisons": [
                    {
                        "name": item["rustType"] + "::" + item["variant"],
                        **{
                            key: item[key]
                            for key in ("rustSha256", "pythonSha256", "equal")
                        },
                    }
                    for item in selected
                ],
            }
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
        "outcome": "passed" if all(item["equal"] for item in comparisons) else "failed",
        "fixtureExecutableSha256": parity.digest_bytes(
            args.rust_executable.read_bytes()
        ),
        "comparisons": comparisons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.output.with_name(args.output.stem + "-results.json")
    raw_path.write_text(json.dumps(result, indent=2) + "\n")
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
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        f"{result['outcome']}: {sum(item['equal'] for item in comparisons)}"
        f"/{len(comparisons)} diagnostic fixtures"
    )
    return 0 if result["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
