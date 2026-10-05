"""Compare Rust-authored public Document/Parse errors with Python metadata.

Build the fixture with ``cargo build -p yosoi --example
python_document_errors_conformance`` then run this script with the example
executable and a verified rustdoc reference. Rust supplies every case input.
"""

from __future__ import annotations

import argparse
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

EXPECTED_FIXTURE_NAMES = {
    "document-id-empty",
    "document-json-empty-payload",
    "document-epoch-zero",
    "document-parse-json-duplicate-key",
    "document-parse-json-truncated",
    "document-parse-html-input-limit",
    "document-profile-serde-incompatible-axes",
}

CASE_EXCEPTION_TARGETS = {
    "document-id-empty": "yosoi.errors.DocumentError",
    "document-json-empty-payload": "yosoi.errors.DocumentError",
    "document-epoch-zero": "yosoi.errors.DocumentError",
    "document-parse-json-duplicate-key": "yosoi.errors.ParseError",
    "document-parse-json-truncated": "yosoi.errors.ParseError",
    "document-parse-html-input-limit": "yosoi.errors.ParseError",
    "document-profile-serde-incompatible-axes": "yosoi.errors.DocumentError",
}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def validate_fixture_set(value: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or value.get("kind") != "yosoi-document-error-fixtures"
        or not isinstance(value.get("cases"), list)
    ):
        raise ValueError("unsupported Rust Document/Parse error fixture output")

    cases = value["cases"]
    names = [item.get("name") for item in cases if isinstance(item, dict)]
    if (
        len(names) != len(cases)
        or len(names) != len(set(names))
        or set(names) != EXPECTED_FIXTURE_NAMES
    ):
        raise ValueError("Rust Document/Parse error fixture cases differ from contract")

    required = {"name", "operationPath", "errorPath", "input", "error"}
    for item in cases:
        if not required.issubset(item):
            raise ValueError(f"incomplete Rust fixture: {item.get('name')}")
        if not isinstance(item["input"], dict) or not isinstance(item["error"], dict):
            raise ValueError(f"invalid Rust fixture values: {item['name']}")
        if not {
            "rust_type",
            "variant",
            "details",
            "message",
            "source_chain",
        }.issubset(item["error"]):
            raise ValueError(f"incomplete Rust error record: {item['name']}")
    return cases


def _resolve_target(target: str) -> type[BaseException]:
    module_name, name = target.rsplit(".", 1)
    value = getattr(importlib.import_module(module_name), name)
    if not isinstance(value, type) or not issubclass(value, BaseException):
        raise TypeError(f"Python error target is not an exception: {target}")
    return value


def _python_input_and_call(fixture: dict[str, Any], ys: Any) -> tuple[dict, Any]:
    from yosoi.scalars import DocumentEpoch, DocumentId

    input_value = fixture["input"]
    name = fixture["name"]
    if name == "document-id-empty":
        return input_value, lambda: DocumentId.try_new(input_value["value"])
    if name == "document-json-empty-payload":
        return input_value, lambda: ys.Document.from_json(
            input_value["id"], input_value["content"]
        )
    if name == "document-epoch-zero":
        return input_value, lambda: DocumentEpoch.try_new(input_value["value"])
    if name in {
        "document-parse-json-duplicate-key",
        "document-parse-json-truncated",
    }:
        document = ys.Document.from_json(input_value["id"], input_value["content"])
        return input_value, document.parse
    if name == "document-parse-html-input-limit":
        documents = ys.policy.Documents(
            max_input_bytes=input_value["policy"]["documents"]["max_input_bytes"]
        )
        policy = ys.Policy(documents=documents)
        document = ys.Document.html(input_value["id"], input_value["content"])
        bound = document.bind(policy)
        return input_value, bound.parse
    if name == "document-profile-serde-incompatible-axes":
        native = importlib.import_module("yosoi._native")
        return input_value, lambda: native.validate_profile(input_value["profile_json"])
    raise ValueError(f"unsupported public Document/Parse fixture: {name}")


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


def compare_fixture(
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
        **(
            {"operationTrait": fixture["operationTrait"]}
            if fixture.get("operationTrait")
            else {}
        ),
        **(
            {"constructionPaths": fixture["constructionPaths"]}
            if fixture.get("constructionPaths")
            else {}
        ),
        "errorPath": fixture["errorPath"],
        **(
            {"errorTypePath": fixture["errorTypePath"]}
            if fixture.get("errorTypePath")
            else {}
        ),
        "rust": rust,
        "python": python,
        "pythonTarget": observed["expectedException"],
        "actualExceptionType": observed["exceptionType"],
        "exceptionMatches": observed["exceptionMatches"],
        "equal": equal,
        "rustSha256": module.digest_json(rust),
        "pythonSha256": module.digest_json(python),
    }


def _evidence_cases(comparisons: list[dict], ledger: dict[str, Any]) -> list[dict]:
    entries = {
        entry["rustPath"]: entry
        for entry in ledger["entries"]
        if entry.get("decision") == "mapped"
    }
    cases = []
    for comparison in comparisons:
        if not comparison["equal"]:
            continue
        roles = [
            ("operation", comparison["operationPath"]),
            ("error", comparison["errorPath"]),
            ("error_type", comparison.get("errorTypePath")),
        ]
        roles.extend(
            ("construction", path)
            for path in comparison.get("constructionPaths", [])
        )
        matched = []
        seen = set()
        for role, path in roles:
            if path is None or path in seen:
                continue
            seen.add(path)
            entry = entries.get(path)
            if entry is None:
                continue
            if entry.get("trait") and entry["trait"] != comparison.get(
                "operationTrait"
            ):
                continue
            matched.append(
                {
                    "role": role,
                    "rustPath": path,
                    "symbolKey": entry["symbolKey"],
                    "pythonTarget": entry["pythonTarget"],
                }
            )
        if not matched:
            continue
        cases.append(
            {
                "testId": "document-errors:" + comparison["name"],
                "outcome": "passed",
                "rustErrorType": comparison["rust"]["error"]["rust_type"],
                "rustVariant": comparison["rust"]["error"]["variant"],
                "comparisons": [
                    {
                        "name": comparison["name"],
                        "rustSha256": comparison["rustSha256"],
                        "pythonSha256": comparison["pythonSha256"],
                        "equal": True,
                    }
                ],
                "matchedSymbols": matched,
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
    fixture_set = validate_fixture_set(json.loads(process.stdout))

    import yosoi as ys

    ledger = parity.load_ledger(args.ledger)
    comparisons = []
    for fixture in fixture_set:
        target = CASE_EXCEPTION_TARGETS[fixture["name"]]
        observed = _observe_python_error(fixture, ys, _resolve_target(target))
        comparisons.append(compare_fixture(fixture, observed, parity))

    passed = all(item["equal"] for item in comparisons)
    source = {
        key: rust[key]
        for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
    }
    python_identity = {
        key: python[key]
        for key in ("surfaceDigest", "implementationDigest", "runtime")
    }
    cases = _evidence_cases(comparisons, ledger)
    result = {
        "schemaVersion": 1,
        "kind": "yosoi-python-rust-conformance-results",
        "runId": str(uuid.uuid4()),
        "outcome": "passed" if passed else "failed",
        "source": source,
        "python": python_identity,
        "cases": cases,
        "comparisons": comparisons,
        "fixtureExecutableSha256": parity.digest_bytes(
            args.rust_executable.read_bytes()
        ),
        "fixtureOutputSha256": parity.digest_bytes(process.stdout.encode("utf-8")),
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
