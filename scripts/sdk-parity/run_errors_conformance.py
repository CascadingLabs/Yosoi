"""Compare real public Rust SDK operation errors with Python native metadata.

Build the fixture with ``cargo build -p yosoi --example python_errors_conformance``
then run this script with the example executable and a verified rustdoc reference.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import subprocess
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import parity

ERROR_TARGET_FALLBACKS = {
    # ActivityId/CaptureId expose this external error type through associated Err.
    "yosoi_types::OccurrenceIdParseError": "yosoi.errors.RequestError",
}
EXPECTED_FIXTURE_NAMES = {
    "request-bound-validate-invalid-scheme",
    "map-bound-validate-invalid-scheme",
    "request-bound-send-invalid-scheme",
    "search-new-empty-query",
    "search-new-513-byte-query",
    "search-bound-validate-no-providers",
    *{
        f"{identity}-{scenario}"
        for identity in ("activity-id", "capture-id")
        for scenario in ("invalid-uuid", "noncanonical", "not-random-v4")
    },
}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _resolve_target(target: str) -> type[BaseException]:
    module_name, name = target.rsplit(".", 1)
    value = getattr(importlib.import_module(module_name), name)
    if not isinstance(value, type) or not issubclass(value, BaseException):
        raise TypeError(f"Python error target is not an exception: {target}")
    return value


def _python_input_and_call(fixture: dict[str, Any], ys: Any) -> tuple[dict, Any]:
    input_value = fixture["input"]
    operation = fixture["operationPath"]
    if operation == "yosoi::request::BoundPageRequest::validate":
        policy = ys.Policy()
        request = ys.request.new(input_value["target"]).bind(policy)
        return input_value, request.check
    if operation == "yosoi::map::MapRequest::validate":
        policy = ys.Policy()
        request = ys.map.new(input_value["seed"]).bind(policy)
        return input_value, request.check
    if operation == "yosoi::request::BoundPageRequest::send":
        policy = ys.Policy()
        request = ys.request.new(input_value["target"]).bind(policy)
        return input_value, lambda: asyncio.run(request.send())
    if operation == "yosoi::search::SearchRequest::new":
        query = input_value["query"]
        observed_bytes = len(query.encode("utf-8"))
        declared_bytes = input_value.get("query_bytes", observed_bytes)
        if observed_bytes != declared_bytes:
            raise ValueError(
                f"{fixture['name']} declares {declared_bytes} query bytes, "
                f"observed {observed_bytes}"
            )
        python_input = {"query": query}
        if "query_bytes" in input_value:
            python_input["query_bytes"] = observed_bytes
        return python_input, lambda: ys.search.new(query)
    if operation == "yosoi::search::BoundSearchRequest::validate":
        policy = ys.Policy(search=ys.policy.Search.disabled())
        request = ys.search.new(input_value["query"]).bind(policy)
        return input_value, request.check
    if operation == "yosoi::request::ActivityId::from_str":
        value = input_value["value"]
        return input_value, lambda: ys.request.ActivityId.from_str(value)
    if operation == "yosoi::request::CaptureId::from_str":
        value = input_value["value"]
        return input_value, lambda: ys.request.CaptureId.from_str(value)
    raise ValueError(f"unsupported public SDK operation: {operation}")


def _observe_python_error(
    fixture: dict[str, Any], ys: Any, expected_error: type[BaseException]
) -> dict[str, Any]:
    from yosoi.errors import rust_error_details

    python_input, call = _python_input_and_call(fixture, ys)
    try:
        call()
    except Exception as error:
        details = rust_error_details(error)
        metadata = None
        if details is not None:
            metadata = {
                "rust_type": details.rust_type,
                "variant": details.variant,
                "details": _plain(details.details),
                "message": str(error),
                "source_chain": list(details.source_chain),
            }
        return {
            "input": python_input,
            "error": metadata,
            "exceptionType": f"{type(error).__module__}.{type(error).__qualname__}",
            "expectedException": (
                f"{expected_error.__module__}.{expected_error.__qualname__}"
            ),
            "exceptionMatches": isinstance(error, expected_error),
        }
    return {
        "input": python_input,
        "error": None,
        "exceptionType": None,
        "expectedException": (
            f"{expected_error.__module__}.{expected_error.__qualname__}"
        ),
        "exceptionMatches": False,
    }


def _compare_fixture(
    fixture: dict[str, Any], observed: dict[str, Any], module: Any
) -> dict[str, Any]:
    rust = {"input": fixture["input"], "error": fixture["error"]}
    python = {"input": observed["input"], "error": observed["error"]}
    equal = (
        observed["exceptionMatches"]
        and observed["error"] is not None
        and rust == python
    )
    return {
        "name": fixture["name"],
        "operationPath": fixture["operationPath"],
        "operationTrait": fixture.get("operationTrait"),
        "errorPath": fixture["errorPath"],
        "rust": rust,
        "python": python,
        "pythonTarget": observed["expectedException"],
        "actualExceptionType": observed["exceptionType"],
        "exceptionMatches": observed["exceptionMatches"],
        "equal": equal,
        "rustSha256": module.digest_json(rust),
        "pythonSha256": module.digest_json(python),
    }


def _mapping_checks(
    entry: dict[str, Any], selected: list[dict[str, Any]]
) -> list[dict]:
    checks = []
    for mapping in entry.get("argumentMappings", []):
        rust_key = mapping["rustArgument"]
        python_key = mapping["pythonArgument"]
        rust_values = [item["rust"]["input"].get(rust_key) for item in selected]
        python_values = [item["python"]["input"].get(python_key) for item in selected]
        complete = all(
            rust_key in item["rust"]["input"] and python_key in item["python"]["input"]
            for item in selected
        )
        checks.append(
            {
                "kind": "argument",
                "key": rust_key,
                "rustSha256": parity.digest_json(rust_values),
                "pythonSha256": parity.digest_json(python_values),
                "equal": complete and rust_values == python_values,
            }
        )
    return checks


def _evidence_cases(comparisons: list[dict], ledger: dict[str, Any]) -> list[dict]:
    """Attribute only exercised operation paths and matched error symbols."""
    entries = {
        entry["rustPath"]: entry
        for entry in ledger["entries"]
        if entry.get("decision") == "mapped" and entry.get("trait") in (None, "FromStr")
    }
    selected_by_path: dict[str, list[dict]] = {}
    for comparison in comparisons:
        if not comparison["equal"]:
            continue
        for path in {comparison["operationPath"], comparison["errorPath"]}:
            entry = entries.get(path)
            if entry is None:
                continue
            if (
                entry.get("trait") == "FromStr"
                and comparison.get("operationTrait") != "FromStr"
            ):
                continue
            selected_by_path.setdefault(path, []).append(comparison)

    cases = []
    for path, selected in sorted(selected_by_path.items()):
        entry = entries[path]
        mapping_checks = _mapping_checks(entry, selected)
        cases.append(
            {
                "testId": "operation-errors:" + path,
                "rustPath": path,
                "symbolKey": entry["symbolKey"],
                "pythonTarget": entry["pythonTarget"],
                "outcome": "passed",
                "comparisons": [
                    {
                        "name": item["name"],
                        "rustSha256": item["rustSha256"],
                        "pythonSha256": item["pythonSha256"],
                        "equal": item["equal"],
                    }
                    for item in selected
                ],
                "mappingChecks": mapping_checks,
                **({"trait": entry["trait"]} if entry.get("trait") else {}),
            }
        )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-executable", type=Path, required=True)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument("--python-root", type=Path, default=Path("python"))
    args = parser.parse_args()

    rust = parity.load_rust_inventory(args.rust_reference)
    python = parity.introspect_python_package(python_root=args.python_root)
    process = subprocess.run(
        [str(args.rust_executable.resolve())],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    fixture_set = json.loads(process.stdout)
    if (
        fixture_set.get("schemaVersion") != 1
        or fixture_set.get("kind") != "yosoi-operation-error-fixtures"
        or not isinstance(fixture_set.get("cases"), list)
    ):
        raise ValueError("unsupported Rust operation error fixture output")
    fixture_names = [case.get("name") for case in fixture_set["cases"]]
    if (
        len(fixture_names) != len(set(fixture_names))
        or set(fixture_names) != EXPECTED_FIXTURE_NAMES
    ):
        raise ValueError("Rust operation error fixture cases differ from the contract")

    import yosoi as ys

    ledger = parity.load_ledger(args.ledger)
    entries = {entry["rustPath"]: entry for entry in ledger["entries"]}
    comparisons = []
    for fixture in fixture_set["cases"]:
        error_path = fixture["errorPath"]
        error_entry = entries.get(error_path)
        if error_entry is None:
            error_entry = entries.get(fixture["error"]["rust_type"])
        target = (
            error_entry["pythonTarget"]
            if error_entry is not None and error_entry.get("decision") == "mapped"
            else ERROR_TARGET_FALLBACKS.get(fixture["error"]["rust_type"])
        )
        if target is None:
            raise ValueError(f"no mapped Python exception target for {error_path}")
        expected_error = _resolve_target(target)
        observed = _observe_python_error(fixture, ys, expected_error)
        comparisons.append(_compare_fixture(fixture, observed, parity))

    passed = all(item["equal"] for item in comparisons)
    source = {
        key: rust[key]
        for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
    }
    python_identity = {
        key: python[key] for key in ("surfaceDigest", "implementationDigest", "runtime")
    }
    cases = _evidence_cases(comparisons, ledger)
    run_id = str(uuid.uuid4())
    result = {
        "schemaVersion": 1,
        "kind": "yosoi-python-rust-conformance-results",
        "runId": run_id,
        "outcome": "passed" if passed else "failed",
        "source": source,
        "python": python_identity,
        "cases": cases,
        "comparisons": comparisons,
        "fixtureExecutableSha256": parity.digest_bytes(
            args.rust_executable.read_bytes()
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.output.with_name(args.output.stem + "-results.json")
    raw_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
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
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "fixtures": len(comparisons),
                "matched": sum(item["equal"] for item in comparisons),
                "attributions": len(cases),
                "outcome": result["outcome"],
                "evidence": str(args.output),
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
