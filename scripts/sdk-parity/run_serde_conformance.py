"""Compare Rust-authored public Serde fixtures with Python SDK JSON codecs.

Build the fixture with ``cargo build -p yosoi --example
python_serde_conformance``. The Rust executable authors and emits every input;
this runner only sends those Rust values to the Python SDK.
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

DEFAULT_METHOD_TARGETS = {
    "yosoi.policy.Redirects",
    "yosoi.scalars.EventLimit",
    "yosoi.scalars.MaximumElapsed",
    "yosoi.scalars.RedirectHopLimit",
}


def resolve_path(value: Any, path: str) -> tuple[bool, Any]:
    """Resolve an object/list path and preserve missing versus JSON null."""
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


def shape_observation(value: Any, expectations: dict[str, Any]) -> dict[str, Any]:
    """Check only explicitly named null and absent paths without normalization."""
    null_paths = []
    for path in expectations.get("nullPaths", []):
        present, observed = resolve_path(value, path)
        null_paths.append(
            {"path": path, "present": present, "isNull": present and observed is None}
        )
    absent_paths = []
    for path in expectations.get("absentPaths", []):
        present, observed = resolve_path(value, path)
        del observed
        absent_paths.append({"path": path, "absent": not present})
    return {
        "nullPaths": null_paths,
        "absentPaths": absent_paths,
        "passed": all(item["isNull"] for item in null_paths)
        and all(item["absent"] for item in absent_paths),
    }


def python_input_for_fixture(fixture: dict[str, Any]) -> tuple[Any, str]:
    """Use Rust's wire input when Rust supports decode, otherwise its output."""
    if fixture.get("decoder_supported"):
        if not fixture.get("wire_input_available"):
            raise ValueError("decoder-supported fixture is missing its Rust wire input")
        return fixture["wire_input"], "rust_wire_input"
    return fixture["rust_output"], "rust_serialized_output"


def load_type_mappings(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["rustPath"]): item
        for item in audit.get("typeMappings", [])
        if item.get("rustPath") and item.get("pythonTarget")
    }


def load_python_type(target: str) -> Any:
    module_name, type_name = target.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), type_name)


def operation_mapping_checks(
    operation: dict[str, Any] | None,
    python_operation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not operation:
        return []
    rust_arguments = operation.get("rustArguments", {})
    python_arguments = (python_operation or {}).get(
        "pythonArguments", operation.get("pythonArguments", {})
    )
    pairs = (
        (("atom", "atom"), ("result_shape", "result_shape"))
        if operation.get("name") == "QuerySpec.new"
        else (("prefix", "prefix"), ("namespace_uri", "uri"))
    )
    checks = []
    for rust_name, python_name in pairs:
        rust_present = rust_name in rust_arguments
        python_present = python_name in python_arguments
        rust_value = rust_arguments.get(rust_name)
        python_value = python_arguments.get(python_name)
        checks.append(
            {
                "rustArgument": rust_name,
                "pythonArgument": python_name,
                "rustSha256": parity.digest_json(rust_value),
                "pythonSha256": parity.digest_json(python_value),
                "equal": (
                    rust_present and python_present and rust_value == python_value
                ),
            }
        )
    return checks


def python_field_observations(
    python_type: Any, value: Any, python_output: Any
) -> dict[str, dict[str, Any]]:
    """Record live Pydantic attributes and their actual JSON dump projections."""
    fields = getattr(python_type, "model_fields", {})
    observations = {}
    if not isinstance(fields, dict):
        return observations
    for field_name, field_info in fields.items():
        serialization_alias = getattr(field_info, "serialization_alias", None)
        alias = serialization_alias or getattr(field_info, "alias", None)
        if not isinstance(alias, str):
            alias = field_name
        item: dict[str, Any] = {
            "pythonField": field_name,
            "serializationAlias": alias,
            "pythonAttributePresent": False,
            "pythonWirePresent": False,
        }
        try:
            attribute = getattr(value, field_name)
            item["pythonAttributePresent"] = True
            item["pythonAttributeValue"] = TypeAdapter(
                field_info.annotation
            ).dump_python(
                attribute,
                mode="json",
                by_alias=True,
                exclude_none=False,
                exclude_defaults=False,
                exclude_unset=False,
            )
        except Exception as error:
            item["pythonAttributeError"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        present, projected = resolve_path(python_output, alias)
        item["pythonWirePresent"] = present
        if present:
            item["pythonWireValue"] = projected
        item["attributeProjectionEqual"] = (
            item["pythonAttributePresent"]
            and present
            and item.get("pythonAttributeValue") == projected
        )
        observations[field_name] = item
    return observations


def observe_python(
    fixture: dict[str, Any], target: str
) -> tuple[Any, Any, dict[str, Any]]:
    """Validate Rust wire data and serialize the corresponding public Python value."""
    python_type = load_python_type(target)
    adapter = TypeAdapter(python_type)
    if fixture.get("construction") == "Rust Default::default":
        value = (
            python_type.default() if target in DEFAULT_METHOD_TARGETS else python_type()
        )
        python_input = None
        input_source = (
            "python_public_default_method"
            if target in DEFAULT_METHOD_TARGETS
            else "python_public_default_constructor"
        )
    else:
        python_input, input_source = python_input_for_fixture(fixture)
        value = adapter.validate_python(python_input)
    operation = fixture.get("operation")
    operation_evidence: dict[str, Any] | None = None
    if operation:
        if operation.get("name") == "QuerySpec.new":
            query_atom_type = load_python_type("yosoi.locators.QueryAtom")
            result_shape_type = load_python_type("yosoi.locators.QueryResultShape")
            python_arguments = {
                "atom": TypeAdapter(query_atom_type).dump_python(
                    value.atom, mode="json"
                ),
                "result_shape": TypeAdapter(result_shape_type).dump_python(
                    value.result_shape, mode="json"
                ),
            }
            value = python_type.new(value.atom, value.result_shape)
        elif operation.get("name") == "QuerySpec.with_namespace":
            arguments = operation.get("pythonArguments", {})
            prefix = arguments["prefix"]
            uri = arguments["uri"]
            python_arguments = {"prefix": prefix, "uri": uri}
            value = value.with_namespace(prefix, uri)
        else:
            raise ValueError(
                f"unsupported mapped Python operation: {operation.get('name')}"
            )
        operation_evidence = {
            "name": operation["name"],
            "pythonArguments": python_arguments,
            "rustArguments": operation.get("rustArguments", {}),
        }

    python_raw_dump = None
    python_unit_observation = None
    rust_unit_observation = fixture.get("unit_observation")
    if rust_unit_observation:
        if rust_unit_observation.get("name") != "MaximumElapsed.as_microseconds":
            raise ValueError(
                "unsupported typed unit observation: "
                f"{rust_unit_observation.get('name')}"
            )
        python_microseconds = value.as_microseconds()
        rust_microseconds = rust_unit_observation["rust_result"]
        python_unit_observation = {
            "name": "MaximumElapsed.as_microseconds",
            "rustResult": rust_microseconds,
            "pythonResult": python_microseconds,
            "equal": rust_microseconds == python_microseconds,
        }
    if target == "yosoi.Policy":
        # Policy's supported wire export is the native Rust-normalized method.
        # Preserve inherited model_dump too, so its tuning difference stays visible.
        python_raw_dump = value.model_dump(mode="json")
        python_output = json.loads(value.to_json())
        serialization_route = "Policy.to_json"
    else:
        python_output = adapter.dump_python(
            value,
            mode="json",
            by_alias=True,
            exclude_none=False,
            exclude_defaults=False,
            exclude_unset=False,
        )
        serialization_route = "TypeAdapter.dump_python(mode=json)"

    return (
        python_input,
        python_output,
        {
            "inputSource": input_source,
            "serializationRoute": serialization_route,
            "operation": operation_evidence,
            "unitObservation": python_unit_observation,
            "rawModelDump": python_raw_dump,
            "fieldObservations": python_field_observations(
                python_type, value, python_output
            ),
        },
    )


def compare_fixture(fixture: dict[str, Any], python_target: str) -> dict[str, Any]:
    rust_output = fixture["rust_output"]
    expectations = fixture.get("shape_expectations") or {}
    rust_shape = shape_observation(rust_output, expectations)
    python_error = None
    python_input = None
    python_output = None
    python_observation: dict[str, Any] = {}
    try:
        python_input, python_output, python_observation = observe_python(
            fixture, python_target
        )
        python_shape = shape_observation(python_output, expectations)
    except Exception as error:
        python_shape = shape_observation(None, expectations)
        python_error = {
            "type": type(error).__name__,
            "message": str(error),
        }

    equal = (
        python_error is None
        and fixture.get("fixture_passed") is True
        and fixture.get("input_source") == "rust"
        and rust_shape["passed"]
        and python_shape["passed"]
        and python_output == rust_output
        and (
            not fixture.get("unit_observation")
            or (python_observation.get("unitObservation") or {}).get("equal") is True
        )
        and all(
            check["equal"]
            for check in operation_mapping_checks(
                fixture.get("operation"), python_observation.get("operation")
            )
        )
    )
    comparison = {
        "name": fixture["name"],
        "rustType": fixture["rust_type"],
        "pythonTarget": python_target,
        "decoderSupported": fixture.get("decoder_supported") is True,
        "construction": fixture.get("construction"),
        "operation": fixture.get("operation"),
        "operationMappingChecks": operation_mapping_checks(
            fixture.get("operation"), python_observation.get("operation")
        ),
        "inputSource": fixture.get("input_source"),
        "wireInputAvailable": fixture.get("wire_input_available") is True,
        "wireInput": fixture.get("wire_input"),
        "rustOutput": rust_output,
        "pythonInputSource": python_observation.get("inputSource"),
        "pythonInput": python_input,
        "pythonOutput": python_output,
        "pythonRawModelDump": python_observation.get("rawModelDump"),
        "pythonSerializationRoute": python_observation.get("serializationRoute"),
        "pythonOperation": python_observation.get("operation"),
        "pythonUnitObservation": python_observation.get("unitObservation"),
        "pythonFieldObservations": python_observation.get("fieldObservations", {}),
        "rustRoundTripPassed": fixture.get("round_trip_passed"),
        "rustShape": rust_shape,
        "pythonShape": python_shape,
        "rustFixturePassed": fixture.get("fixture_passed") is True,
        "pythonError": python_error,
        "equal": equal,
        "outcome": "passed" if equal else "failed",
        "rustSha256": parity.digest_json(rust_output),
        "pythonSha256": (
            parity.digest_json(python_output) if python_error is None else None
        ),
    }
    if comparison["pythonRawModelDump"] is not None:
        comparison["rawModelDumpEqual"] = (
            comparison["pythonRawModelDump"] == rust_output
        )
        comparison["rawModelDumpOutcome"] = (
            "passed" if comparison["rawModelDumpEqual"] else "failed"
        )
    return comparison


def standard_evidence_cases(
    ledger: dict[str, Any],
    comparisons: list[dict[str, Any]],
    rust_inventory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Bind exact JSON observations to public types and called QuerySpec methods."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for comparison in comparisons:
        if comparison.get("rustType"):
            by_type.setdefault(comparison["rustType"], []).append(comparison)

    cases = []
    for entry in ledger.get("entries", []):
        if entry.get("decision") != "mapped" or not str(
            entry.get("symbolKey", "")
        ).startswith("page:"):
            continue
        rust_path = entry.get("rustPath")
        selected = by_type.get(rust_path, [])
        if not selected:
            continue

        mapping_checks = []
        mappings_are_supported = not (
            entry.get("argumentMappings")
            or entry.get("fixedArguments")
            or entry.get("cardinality")
        )
        for mapping in entry.get("defaults", []):
            default_cases = [
                item
                for item in selected
                if item.get("construction") == "Rust Default::default"
            ]
            rust_values = [item.get("rustOutput") for item in default_cases]
            python_values = [item.get("pythonOutput") for item in default_cases]
            present = bool(default_cases)
            mapping_checks.append(
                {
                    "kind": "default",
                    "key": mapping["id"],
                    "rustSha256": parity.digest_json(rust_values),
                    "pythonSha256": parity.digest_json(python_values),
                    "equal": present and rust_values == python_values,
                }
            )

        for mapping in entry.get("units", []):
            unit_observations = [
                item.get("pythonUnitObservation")
                for item in selected
                if (item.get("pythonUnitObservation") or {}).get("name")
                == "MaximumElapsed.as_microseconds"
            ]
            unit_observations = [item for item in unit_observations if item is not None]
            if not unit_observations:
                mappings_are_supported = False
                continue
            rust_values = [item.get("rustResult") for item in unit_observations]
            python_values = [item.get("pythonResult") for item in unit_observations]
            mapping_checks.append(
                {
                    "kind": "unit",
                    "key": mapping["id"],
                    "rustSha256": parity.digest_json(rust_values),
                    "pythonSha256": parity.digest_json(python_values),
                    "equal": all(
                        item.get("equal") is True for item in unit_observations
                    )
                    and rust_values == python_values,
                    "observation": "MaximumElapsed.as_microseconds",
                }
            )

        if not mappings_are_supported:
            continue
        assertions = [
            {
                "name": item["name"],
                "rustSha256": item.get("rustSha256"),
                "pythonSha256": item.get("pythonSha256"),
                "equal": item.get("equal") is True
                and item.get("pythonTarget") == entry.get("pythonTarget"),
            }
            for item in selected
        ]
        passes = all(item["equal"] for item in assertions) and all(
            check["equal"] for check in mapping_checks
        )
        case = {
            "testId": "serde-json-type:" + str(rust_path),
            "rustPath": rust_path,
            "pythonTarget": entry.get("pythonTarget"),
            "outcome": "passed" if passes else "failed",
            "comparisons": assertions,
            "mappingChecks": mapping_checks,
        }
        for field in ("symbolKey", "trait"):
            if entry.get(field):
                case[field] = entry[field]
        cases.append(case)

    operation_paths = {
        "QuerySpec.new": "yosoi::locators::QuerySpec::new",
        "QuerySpec.with_namespace": "yosoi::locators::QuerySpec::with_namespace",
    }
    ledger_by_path = {
        entry.get("rustPath"): entry
        for entry in ledger.get("entries", [])
        if entry.get("decision") == "mapped"
    }
    for operation_name, rust_path in operation_paths.items():
        entry = ledger_by_path.get(rust_path)
        if entry is None:
            continue
        comparison = next(
            (
                item
                for item in comparisons
                if (item.get("pythonOperation") or {}).get("name") == operation_name
            ),
            None,
        )
        if comparison is None:
            continue
        observed_checks = comparison.get("operationMappingChecks", [])
        mapping_checks = []
        for mapping in entry.get("argumentMappings", []):
            observed = next(
                (
                    item
                    for item in observed_checks
                    if item.get("rustArgument") == mapping["rustArgument"]
                    and item.get("pythonArgument") == mapping["pythonArgument"]
                ),
                None,
            )
            mapping_checks.append(
                {
                    "kind": "argument",
                    "key": mapping["rustArgument"],
                    "rustSha256": (observed or {}).get("rustSha256"),
                    "pythonSha256": (observed or {}).get("pythonSha256"),
                    "equal": (observed or {}).get("equal") is True,
                }
            )
        passes = comparison.get("equal") is True and all(
            check["equal"] for check in mapping_checks
        )
        case = {
            "testId": "serde-json-operation:" + rust_path,
            "rustPath": rust_path,
            "pythonTarget": entry.get("pythonTarget"),
            "outcome": "passed" if passes else "failed",
            "comparisons": [
                {
                    "name": comparison["name"],
                    "rustSha256": comparison.get("rustSha256"),
                    "pythonSha256": comparison.get("pythonSha256"),
                    "equal": comparison.get("equal") is True
                    and (comparison.get("pythonOperation") or {}).get("name")
                    == operation_name,
                }
            ],
            "mappingChecks": mapping_checks,
            "symbolKey": entry["symbolKey"],
        }
        if entry.get("trait"):
            case["trait"] = entry["trait"]
        cases.append(case)

    if rust_inventory is not None:
        cases.extend(struct_field_evidence_cases(ledger, comparisons, rust_inventory))
    return cases


def struct_field_evidence_cases(
    ledger: dict[str, Any],
    comparisons: list[dict[str, Any]],
    rust_inventory: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare mapped struct fields using compiler, ledger, and live model evidence."""
    entries = ledger.get("entries", [])
    entries_by_symbol = {item.get("symbolKey"): item for item in entries}
    entries_by_path = {item.get("rustPath"): item for item in entries}
    cases = []
    for rust_field in rust_inventory.get("items", []):
        if rust_field.get("kind") != "struct_field":
            continue
        field_entry = entries_by_symbol.get(rust_field.get("symbolKey"))
        parent_path = rust_field.get("parentRustPath")
        parent_entry = entries_by_path.get(parent_path)
        if (
            field_entry is None
            or field_entry.get("decision") != "mapped"
            or parent_entry is None
            or parent_entry.get("decision") != "mapped"
        ):
            continue

        # These mappings need independent observations that this runner does not
        # collect. Do not turn their descriptive ledger values into passing hashes.
        if any(
            field_entry.get(name)
            for name in ("units", "cardinality", "argumentMappings", "fixedArguments")
        ):
            continue

        rust_path = rust_field.get("rustPath")
        rust_field_name = str(rust_field.get("id", "")).rsplit("::", 1)[-1]
        python_target = field_entry.get("pythonTarget")
        python_parent_target, separator, python_field_name = str(
            python_target or ""
        ).rpartition(".")
        if (
            not rust_path
            or rust_path != f"{parent_path}::{rust_field_name}"
            or not separator
            or python_parent_target != parent_entry.get("pythonTarget")
        ):
            continue

        selected = [
            item
            for item in comparisons
            if item.get("rustType") == parent_path
            and item.get("pythonTarget") == parent_entry.get("pythonTarget")
            and item.get("inputSource") == "rust"
        ]
        if not selected:
            continue
        if field_entry.get("defaults") and not any(
            item.get("construction") == "Rust Default::default"
            and item.get("pythonInputSource")
            in {"python_public_default_method", "python_public_default_constructor"}
            for item in selected
        ):
            continue

        field_checks = []
        for item in selected:
            observation = item.get("pythonFieldObservations", {}).get(
                python_field_name, {}
            )
            python_alias = observation.get("serializationAlias")
            rust_output = item.get("rustOutput")
            python_present = observation.get("pythonWirePresent") is True
            rust_keys = []
            if isinstance(rust_output, dict):
                for key in dict.fromkeys((rust_field_name, python_alias)):
                    if isinstance(key, str) and key in rust_output:
                        rust_keys.append(key)
            rust_present = len(rust_keys) == 1
            if not rust_keys and not python_present and item.get("equal") is True:
                # A field omitted by both serializers supplies no observation
                # of its typed value. Other fixtures can verify its accessor.
                continue
            rust_wire_key = rust_keys[0] if rust_present else None
            rust_value = rust_output.get(rust_wire_key) if rust_present else None
            python_attribute_present = observation.get("pythonAttributePresent") is True
            python_value = observation.get("pythonAttributeValue")
            equal = (
                item.get("rustFixturePassed") is True
                and item.get("pythonError") is None
                and rust_present
                and python_present
                and python_attribute_present
                and observation.get("attributeProjectionEqual") is True
                and rust_value == python_value
                and rust_value == observation.get("pythonWireValue")
            )
            if not rust_present:
                reason = "Rust field wire key is absent or ambiguous"
            elif not python_present:
                reason = "Python serialization alias is absent"
            elif not python_attribute_present:
                reason = "Python model attribute is absent"
            elif not observation.get("attributeProjectionEqual"):
                reason = "Python attribute does not match its actual dump projection"
            elif not equal:
                reason = "observed Rust and Python field values differ"
            else:
                reason = None
            field_checks.append(
                {
                    "name": item.get("name"),
                    "construction": item.get("construction"),
                    "rustField": rust_field_name,
                    "rustWireKey": rust_wire_key,
                    "rustPresent": rust_present,
                    "pythonField": python_field_name,
                    "pythonSerializationAlias": python_alias,
                    "pythonAttributePresent": python_attribute_present,
                    "pythonPresent": python_present,
                    "rustSha256": (
                        parity.digest_json(rust_value) if rust_present else None
                    ),
                    "pythonSha256": (
                        parity.digest_json(python_value)
                        if python_attribute_present
                        else None
                    ),
                    "equal": equal,
                    "reason": reason,
                }
            )

        if not field_checks:
            continue

        # A field-specific default mapping is supported only by an independently
        # constructed Rust default and Python public default observation.
        for default_mapping in field_entry.get("defaults", []):
            default_checks = [
                check
                for check in field_checks
                if check.get("construction") == "Rust Default::default"
            ]
            if not default_checks:
                field_checks.append(
                    {
                        "name": "default:" + str(default_mapping.get("id")),
                        "rustField": rust_field_name,
                        "pythonField": python_field_name,
                        "equal": False,
                        "reason": "no independent default fixture observation",
                    }
                )

        passed = bool(field_checks) and all(
            check.get("equal") is True for check in field_checks
        )
        cases.append(
            {
                "testId": "serde-json-field:" + str(rust_path),
                "rustPath": rust_path,
                "parentRustPath": parent_path,
                "pythonTarget": python_target,
                "rustField": rust_field_name,
                "pythonField": python_field_name,
                "outcome": "passed" if passed else "failed",
                "comparisons": field_checks,
                "mappingChecks": [],
                "symbolKey": field_entry.get("symbolKey"),
            }
        )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument(
        "--serde-audit",
        type=Path,
        default=Path("python/parity/json-type-mappings.json"),
    )
    args = parser.parse_args()

    process = subprocess.run(
        [str(args.rust_executable.resolve())],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    fixture_document = json.loads(process.stdout)
    if (
        fixture_document.get("schema_version") != 1
        or fixture_document.get("kind") != "yosoi-python-rust-serde-fixtures"
        or not isinstance(fixture_document.get("fixtures"), list)
    ):
        raise ValueError("Rust executable returned an unsupported fixture document")

    audit_bytes = args.serde_audit.read_bytes()
    audit = json.loads(audit_bytes)
    mappings = load_type_mappings(audit)
    comparisons = []
    for fixture in fixture_document["fixtures"]:
        rust_type = fixture["rust_type"]
        mapping = mappings.get(rust_type)
        if mapping is None:
            comparisons.append(
                {
                    "name": fixture.get("name"),
                    "rustType": rust_type,
                    "outcome": "failed",
                    "equal": False,
                    "pythonError": {
                        "type": "UnmappedRustType",
                        "message": (
                            "canonical Rust SDK type is absent from serde audit "
                            "typeMappings"
                        ),
                    },
                }
            )
            continue
        comparisons.append(compare_fixture(fixture, mapping["pythonTarget"]))

    rust = parity.load_rust_inventory(args.rust_reference)
    python = parity.introspect_python_package()
    passed = sum(item.get("equal") is True for item in comparisons)
    ledger = parity.load_ledger(args.ledger)
    cases = standard_evidence_cases(ledger, comparisons, rust)
    cases_passed = bool(cases) and all(item["outcome"] == "passed" for item in cases)
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
        "serdeAudit": {
            "path": str(args.serde_audit),
            "sha256": parity.digest_bytes(audit_bytes),
            "auditDate": audit.get("auditDate"),
            "classification": audit.get("classification"),
        },
        "scope": {
            "format": "serde_json",
            "limitations": [
                "Covers typed JSON wire behavior only; it does not certify arbitrary "
                "Serde Serializer/Deserializer formats or downstream custom "
                "implementations."
            ],
        },
        "comparisons": comparisons,
        "cases": cases,
        "outcome": (
            "passed" if passed == len(comparisons) and cases_passed else "failed"
        ),
        "fixtureExecutableSha256": parity.digest_bytes(
            args.rust_executable.read_bytes()
        ),
        "fixtureOutputSha256": parity.digest_bytes(process.stdout.encode("utf-8")),
        "fixtureCount": len(fixture_document["fixtures"]),
        "passingFixtureCount": passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.output.with_name(args.output.stem + "-results.json")
    raw_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    evidence = {
        key: result[key]
        for key in (
            "schemaVersion",
            "runId",
            "outcome",
            "source",
            "python",
            "serdeAudit",
            "scope",
            "cases",
            "fixtureCount",
            "passingFixtureCount",
        )
    }
    evidence.update(
        kind="yosoi-python-rust-conformance",
        executedAt=datetime.now(UTC).isoformat(),
        runner={"command": [sys.executable, *sys.argv]},
        resultArtifact={
            "path": raw_path.name,
            "sha256": parity.digest_bytes(raw_path.read_bytes()),
        },
        fixtureExecutableSha256=result["fixtureExecutableSha256"],
        fixtureOutputSha256=result["fixtureOutputSha256"],
    )
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(
        f"{result['outcome']}: {passed}/{len(comparisons)} serde fixtures; "
        f"{sum(item['outcome'] == 'passed' for item in cases)}/{len(cases)} "
        "standard evidence cases"
    )
    return 0 if result["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
