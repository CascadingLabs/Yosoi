"""Compare Rust-authored WebTarget conversions with Python's raw target scalar.

Build the fixture with ``cargo build -p yosoi --example
python_webtarget_conformance``. The runner passes Rust-authored strings to
``yosoi.request.WebTarget.new`` and compares its ``as_str()`` result exactly.
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

import parity

OPERATION_PATH = "yosoi::request::WebTarget::from"
AS_REF_PATH = "yosoi::request::WebTarget::as_ref"
NEW_PATH = "yosoi::request::WebTarget::new"
AS_STR_PATH = "yosoi::request::WebTarget::as_str"
WEB_TARGET_PATH = "yosoi::request::WebTarget"
PYTHON_NEW_TARGET = "yosoi.request.WebTarget.new"
PYTHON_AS_STR_TARGET = "yosoi.request.WebTarget.as_str"

EXPECTED_VALUES = {
    "unicode-url-idn": "https://例え.テスト/道?q=雪",
    "unicode-url-path": "https://example.com/路径/naïve",
    "empty": "",
    "invalid-authored-text": "  not a URL/雪  ",
}
EXPECTED_CONVERSIONS = {
    "from-str": "&str",
    "from-string": "String",
    "from-string-ref": "&String",
    "from-box-str": "Box<str>",
    "from-cow-borrowed": "Cow<'_, str>",
    "from-cow-owned": "Cow<'_, str>",
}


def validate_fixture_set(value: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or value.get("kind") != "yosoi-web-target-conversion-fixtures"
        or not isinstance(value.get("cases"), list)
    ):
        raise ValueError("unsupported Rust WebTarget conversion fixture output")

    cases = value["cases"]
    names = [item.get("name") for item in cases if isinstance(item, dict)]
    expected_names = {
        f"{value_name}/{conversion}"
        for value_name in EXPECTED_VALUES
        for conversion in EXPECTED_CONVERSIONS
    }
    if (
        len(names) != len(cases)
        or len(names) != len(set(names))
        or set(names) != expected_names
    ):
        raise ValueError("Rust WebTarget fixture cases differ from contract")

    required = {
        "name",
        "valueName",
        "conversion",
        "rustArgumentType",
        "operationPath",
        "operationTrait",
        "asRefPath",
        "asRefTrait",
        "newPath",
        "asStrPath",
        "input",
        "raw",
        "asRefRaw",
        "newRaw",
        "asStrRaw",
        "fixturePassed",
    }
    for item in cases:
        if not required.issubset(item):
            raise ValueError(f"incomplete Rust fixture: {item.get('name')}")
        value_name = item["valueName"]
        conversion = item["conversion"]
        if value_name not in EXPECTED_VALUES or conversion not in EXPECTED_CONVERSIONS:
            raise ValueError(f"unknown Rust fixture dimensions: {item['name']}")
        if (
            item["name"] != f"{value_name}/{conversion}"
            or item["rustArgumentType"] != EXPECTED_CONVERSIONS[conversion]
            or item["operationPath"] != OPERATION_PATH
            or item["operationTrait"] != "From"
            or item["asRefPath"] != AS_REF_PATH
            or item["asRefTrait"] != "AsRef"
            or item["newPath"] != NEW_PATH
            or item["asStrPath"] != AS_STR_PATH
            or item["input"] != EXPECTED_VALUES[value_name]
            or item["raw"] != item["input"]
            or item["asRefRaw"] != item["input"]
            or item["newRaw"] != item["input"]
            or item["asStrRaw"] != item["input"]
            or item["fixturePassed"] is not True
        ):
            raise ValueError(
                f"Rust WebTarget fixture failed its raw-text contract: {item['name']}"
            )
    return cases


def _compact_type(value: str) -> str:
    value = "".join(value.split())
    for prefix in (
        "std::string::",
        "alloc::string::",
        "std::boxed::",
        "alloc::boxed::",
    ):
        value = value.replace(prefix, "")
    value = value.replace("std::borrow::", "").replace("alloc::borrow::", "")
    return value


def _type_matches_conversion(argument_type: str, conversion: str) -> bool:
    actual = _compact_type(argument_type)
    expected = EXPECTED_CONVERSIONS[conversion]
    if conversion == "from-cow-owned" or conversion == "from-cow-borrowed":
        return actual.startswith("Cow<") and actual.endswith(",str>")
    return actual == _compact_type(expected)


def _conversion_item(
    rust: dict[str, Any], fixture: dict[str, Any]
) -> dict[str, Any] | None:
    matches = []
    for item in rust.get("items", []):
        if (
            item.get("rustPath") != fixture["operationPath"]
            or item.get("trait") != fixture["operationTrait"]
            or item.get("kind") != "function"
        ):
            continue
        arguments = [
            argument
            for argument in item.get("rustArguments", [])
            if not argument.get("receiver")
        ]
        if len(arguments) == 1 and _type_matches_conversion(
            arguments[0].get("type", ""), fixture["conversion"]
        ):
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _inventory_item(
    rust: dict[str, Any], path: str, trait: str
) -> dict[str, Any] | None:
    matches = [
        item
        for item in rust.get("items", [])
        if item.get("rustPath") == path and item.get("trait") == trait
    ]
    return matches[0] if len(matches) == 1 else None


def _inherent_item(rust: dict[str, Any], path: str) -> dict[str, Any] | None:
    matches = [
        item
        for item in rust.get("items", [])
        if item.get("rustPath") == path and item.get("trait") is None
    ]
    return matches[0] if len(matches) == 1 else None


def mapping_recommendations(
    rust: dict[str, Any], python: dict[str, Any], ledger: dict[str, Any]
) -> list[dict[str, Any]]:
    """Recommend checker-shaped rows only for exact compiler inventory items."""
    ledger_by_key = {
        entry.get("symbolKey"): entry
        for entry in ledger.get("entries", [])
        if entry.get("symbolKey")
    }
    python_targets = python.get("objects", {})
    recommendations: list[dict[str, Any]] = []
    for item in rust.get("items", []):
        rust_path = item.get("rustPath")
        trait = item.get("trait")
        if rust_path == OPERATION_PATH and trait == "From":
            arguments = [
                argument
                for argument in item.get("rustArguments", [])
                if not argument.get("receiver")
            ]
            python_target = PYTHON_NEW_TARGET
            if len(arguments) != 1:
                continue
            recommendation = {
                "rustPath": rust_path,
                "symbolKey": item["symbolKey"],
                "trait": trait,
                "decision": "mapped",
                "pythonTarget": python_target,
                "argumentMappings": [
                    {
                        "rustArgument": arguments[0]["name"],
                        "pythonArgument": "value",
                        "conversion": (
                            f"{arguments[0]['type']} maps to Python str; preserve "
                            "the authored target text"
                        ),
                    }
                ],
                "defaults": [],
                "units": [],
                "cardinality": [],
                "semanticEquivalent": (
                    "From string-like input maps to WebTarget.new(value); "
                    "construction preserves text without URL preparation."
                ),
                "rationale": (
                    "This exact compiler-discovered From impl has an equivalent "
                    "Python WebTarget.new operation with the same raw authored text."
                ),
            }
        elif rust_path == AS_REF_PATH and trait == "AsRef":
            python_target = PYTHON_AS_STR_TARGET
            recommendation = {
                "rustPath": rust_path,
                "symbolKey": item["symbolKey"],
                "trait": trait,
                "decision": "mapped",
                "pythonTarget": python_target,
                "argumentMappings": [],
                "defaults": [],
                "units": [],
                "cardinality": [],
                "semanticEquivalent": (
                    "AsRef<str> returns the authored target text exposed by as_str()."
                ),
                "rationale": (
                    "This exact compiler-discovered AsRef impl returns the same raw "
                    "text as the Python WebTarget.as_str method."
                ),
            }
        else:
            continue

        if python_target not in python_targets:
            continue
        existing = ledger_by_key.get(item.get("symbolKey"))
        if (
            existing
            and existing.get("decision") == "mapped"
            and existing.get("rustPath") == rust_path
            and existing.get("trait") == trait
            and existing.get("pythonTarget") == python_target
        ):
            continue
        recommendations.append(recommendation)
    return recommendations


def observe_python(fixture: dict[str, Any]) -> dict[str, Any]:
    request = importlib.import_module("yosoi.request")
    target = request.WebTarget.new(fixture["input"])
    return {
        "input": fixture["input"],
        "raw": target.as_str(),
        "targetType": f"{type(target).__module__}.{type(target).__qualname__}",
    }


def compare_fixture(
    fixture: dict[str, Any],
    observed: dict[str, Any],
    rust_item: dict[str, Any] | None,
    as_ref_item: dict[str, Any] | None,
    new_item: dict[str, Any] | None,
    as_str_item: dict[str, Any] | None,
    module: Any,
) -> dict[str, Any]:
    rust = {
        "input": fixture["input"],
        "raw": fixture["raw"],
        "asRefRaw": fixture["asRefRaw"],
        "newRaw": fixture["newRaw"],
        "asStrRaw": fixture["asStrRaw"],
    }
    python = {"input": observed["input"], "raw": observed["raw"]}
    equal = (
        fixture["fixturePassed"] is True
        and fixture["input"]
        == fixture["raw"]
        == fixture["asRefRaw"]
        == fixture["newRaw"]
        == fixture["asStrRaw"]
        and observed["input"] == observed["raw"] == fixture["input"]
    )
    rust_hash = module.digest_json(rust["raw"])
    python_hash = module.digest_json(python["raw"])
    as_ref_hash = module.digest_json(rust["asRefRaw"])
    return {
        "name": fixture["name"],
        "valueName": fixture["valueName"],
        "conversion": fixture["conversion"],
        "rustArgumentType": fixture["rustArgumentType"],
        "operationPath": fixture["operationPath"],
        "operationTrait": fixture["operationTrait"],
        "operationSymbolKey": rust_item.get("symbolKey") if rust_item else None,
        "asRefPath": fixture["asRefPath"],
        "asRefTrait": fixture["asRefTrait"],
        "asRefSymbolKey": as_ref_item.get("symbolKey") if as_ref_item else None,
        "newPath": fixture["newPath"],
        "newSymbolKey": new_item.get("symbolKey") if new_item else None,
        "asStrPath": fixture["asStrPath"],
        "asStrSymbolKey": as_str_item.get("symbolKey") if as_str_item else None,
        "rust": rust,
        "python": python,
        "pythonTarget": PYTHON_NEW_TARGET,
        "pythonAsRefTarget": PYTHON_AS_STR_TARGET,
        "pythonType": observed["targetType"],
        "rustSha256": rust_hash,
        "pythonSha256": python_hash,
        "asRefSha256": as_ref_hash,
        "asRefMatchesPython": rust["asRefRaw"] == python["raw"],
        "equal": equal,
    }


def _mapping_check(
    entry: dict[str, Any], rust_argument: str, python_argument: str
) -> list[dict[str, Any]]:
    checks = []
    for mapping in entry.get("argumentMappings", []):
        supported = (
            mapping.get("rustArgument") == "value"
            and mapping.get("pythonArgument") == "value"
        )
        rust_value = rust_argument if supported else None
        python_value = python_argument if supported else None
        checks.append(
            {
                "kind": "argument",
                "key": mapping["rustArgument"],
                "rustSha256": parity.digest_json(rust_value),
                "pythonSha256": parity.digest_json(python_value),
                "equal": supported and rust_value == python_value,
            }
        )
    for mapping in entry.get("defaults", []):
        checks.append(
            {
                "kind": "default",
                "key": mapping["id"],
                "rustSha256": parity.digest_json(None),
                "pythonSha256": parity.digest_json(None),
                "equal": False,
            }
        )
    for field, kind in (("units", "unit"), ("cardinality", "cardinality")):
        for mapping in entry.get(field, []):
            checks.append(
                {
                    "kind": kind,
                    "key": mapping["id"],
                    "rustSha256": parity.digest_json(None),
                    "pythonSha256": parity.digest_json(None),
                    "equal": False,
                }
            )
    return checks


def evidence_cases(
    ledger: dict[str, Any],
    comparisons: list[dict[str, Any]],
    rust: dict[str, Any],
) -> list[dict[str, Any]]:
    entries = {
        entry.get("symbolKey"): entry
        for entry in ledger.get("entries", [])
        if entry.get("decision") == "mapped" and entry.get("symbolKey")
    }
    cases = []
    for comparison in comparisons:
        for role, symbol_key, path, trait, rust_value, python_value in (
            (
                "from",
                comparison.get("operationSymbolKey"),
                comparison["operationPath"],
                comparison["operationTrait"],
                comparison["rust"]["raw"],
                comparison["python"]["raw"],
            ),
            (
                "as-ref",
                comparison.get("asRefSymbolKey"),
                comparison["asRefPath"],
                comparison["asRefTrait"],
                comparison["rust"]["asRefRaw"],
                comparison["python"]["raw"],
            ),
            (
                "new",
                comparison.get("newSymbolKey"),
                comparison["newPath"],
                None,
                comparison["rust"]["newRaw"],
                comparison["python"]["raw"],
            ),
            (
                "as-str",
                comparison.get("asStrSymbolKey"),
                comparison["asStrPath"],
                None,
                comparison["rust"]["asStrRaw"],
                comparison["python"]["raw"],
            ),
        ):
            item = next(
                (
                    candidate
                    for candidate in rust.get("items", [])
                    if candidate.get("symbolKey") == symbol_key
                    and candidate.get("rustPath") == path
                    and candidate.get("trait") == trait
                ),
                None,
            )
            entry = entries.get(symbol_key)
            expected_target = (
                PYTHON_NEW_TARGET if role in {"from", "new"} else PYTHON_AS_STR_TARGET
            )
            if (
                item is None
                or entry is None
                or entry.get("rustPath") != path
                or entry.get("trait") != trait
                or entry.get("pythonTarget") != expected_target
            ):
                continue
            mapping_checks = _mapping_check(
                entry, comparison["rust"]["input"], comparison["python"]["input"]
            )
            equal = (
                comparison["equal"]
                and rust_value == python_value
                and all(check["equal"] for check in mapping_checks)
            )
            case = {
                "testId": f"webtarget-conversion:{comparison['name']}:{role}",
                "rustPath": path,
                "pythonTarget": entry["pythonTarget"],
                "outcome": "passed" if equal else "failed",
                "comparisons": [
                    {
                        "name": comparison["name"] + ":" + role,
                        "rustSha256": parity.digest_json(rust_value),
                        "pythonSha256": parity.digest_json(python_value),
                        "equal": rust_value == python_value,
                    }
                ],
                "mappingChecks": mapping_checks,
                "symbolKey": symbol_key,
                "trait": trait,
            }
            cases.append(case)
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
    fixtures = validate_fixture_set(json.loads(process.stdout))
    if str(args.python_root.resolve()) not in sys.path:
        sys.path.insert(0, str(args.python_root.resolve()))
    ledger = parity.load_ledger(args.ledger)

    comparisons = []
    for fixture in fixtures:
        observed = observe_python(fixture)
        comparisons.append(
            compare_fixture(
                fixture,
                observed,
                _conversion_item(rust, fixture),
                _inventory_item(rust, fixture["asRefPath"], fixture["asRefTrait"]),
                _inherent_item(rust, fixture["newPath"]),
                _inherent_item(rust, fixture["asStrPath"]),
                parity,
            )
        )

    cases = evidence_cases(ledger, comparisons, rust)
    passing = all(item["equal"] for item in comparisons)
    result = {
        "schemaVersion": 1,
        "kind": "yosoi-python-rust-conformance-results",
        "runId": str(uuid.uuid4()),
        "outcome": "passed" if passing else "failed",
        "source": {
            key: rust[key]
            for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
        },
        "python": {
            key: python[key]
            for key in ("surfaceDigest", "implementationDigest", "runtime")
        },
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
    return 0 if result["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
