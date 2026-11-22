"""Refresh reviewed image mappings from compiler IR and the installed Python SDK.

The command keeps the complete SDK denominator and compact Surface include.
Existing mappings retain their semantics; new image declarations use the
explicit source-backed mapping table. Missing counterparts stop the refresh.
No conformance result or behavioral evidence is manufactured here.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import image_surface_mappings
import sdk_contract
import seed_ledger
from run_sdk_parity import _assert_installed_package

import parity

REVIEWED_SIGNATURE_CHANGES = {
    "yosoi::surface::ArchivedSource::content_base64",
    "yosoi::surface::ArchivedSource::profile",
}


def _network_profile_mapping(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Map the two typed network-profile additions already in this source IR."""
    path = item["rustPath"]
    if path == "yosoi::DocumentProfile::network_observation_v1":
        target = "yosoi.documents.DocumentProfile.network_observation"
        entry = seed_ledger._entry(
            item,
            target,
            python["targets"][target],
            python,
            "Rust's network source profile is the same checked Python profile "
            "with source representation, JSON format and network schema.",
        )
        return entry
    if path == "yosoi::documents::DocumentSchemaProfile::YosoiNetworkObservationV1":
        target = "yosoi.documents.DocumentProfile.schema_profile"
        entry = seed_ledger._entry(
            item,
            target,
            python["targets"][target],
            python,
            "The network schema enum variant is retained as the exact public "
            "Python profile literal yosoi_network_observation_v1.",
        )
        if entry is not None:
            entry["defaults"] = [
                {
                    "id": "variant-tag:schema_profile",
                    "rust": "variant YosoiNetworkObservationV1",
                    "python": "schema_profile=yosoi_network_observation_v1",
                }
            ]
        return entry
    return None


def refresh(
    rust: dict[str, Any], python: dict[str, Any], ledger: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Keep matching reviewed entries and explicitly map new source declarations."""
    result = copy.deepcopy(ledger)
    entries = []
    for item in rust["items"]:
        candidates = [
            row
            for row in ledger["entries"]
            if row["rustPath"] == item["rustPath"]
            and sdk_contract._ledger_trait(row) == item.get("trait")
            and sdk_contract._ledger_kind(row) in {None, item["kind"]}
        ]
        exact = [row for row in candidates if row.get("symbolKey") == item["symbolKey"]]
        signature = [
            row
            for row in candidates
            if sdk_contract._ledger_signature_digest(row)
            == sdk_contract._digest_text(item.get("signature") or "")
        ]
        selected = exact or signature
        if not selected and candidates:
            if (
                item["rustPath"] not in REVIEWED_SIGNATURE_CHANGES
                or len(candidates) != 1
            ):
                raise ValueError(
                    f"unreviewed Rust signature change: {item['rustPath']}"
                )
            selected = candidates
        refreshed = _network_profile_mapping(item, python)
        if (
            refreshed is None
            and selected
            and str(selected[0].get("rationale", "")).startswith(
                "Python retains the same typed pixels"
            )
        ):
            refreshed = image_surface_mappings.image_mapping(item, python)
        if refreshed is not None:
            entries.append(refreshed)
            continue
        if len(selected) == 1:
            row = copy.deepcopy(selected[0])
            row["symbolKey"] = item["symbolKey"]
            entries.append(row)
        elif sdk_contract._expected_classification(item) == "sdk":
            row = image_surface_mappings.image_mapping(
                item, python
            ) or _network_profile_mapping(item, python)
            if row is not None:
                entries.append(row)
    result["entries"] = entries
    sdk_contract._pin_ledger(result, rust, python)
    report = parity.build_report(rust, python, result)
    contract = sdk_contract.build_contract(report)
    missing = [
        row["id"]
        for row in contract["declarations"]
        if row["classification"] == "sdk"
        and row["mapping"]["decision"] not in {"mapped", "language-specific"}
    ]
    if missing:
        raise ValueError("unresolved SDK declarations: " + ", ".join(missing))
    sdk_contract._validate_contract(contract)
    semantic = sdk_contract.evaluate_contract(contract, rust, python, report, [], [])
    if not semantic["mappingStatus"]["complete"]:
        raise ValueError(
            "invalid refreshed mapping semantics: "
            + json.dumps(semantic["mappingStatus"])
        )
    return result, contract, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument(
        "--contract", type=Path, default=Path("python/parity/sdk-contract.json")
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    _assert_installed_package()
    rust = parity.load_rust_inventory(args.rust_reference)
    python = parity.introspect_python_package()
    stored_ledger = parity.read_json(args.ledger)
    stored_contract = parity.read_json(args.contract)
    original = sdk_contract.load_contract(args.contract)
    ledger = parity.load_ledger(args.ledger)
    fresh_ledger, fresh_contract, report = refresh(rust, python, ledger)
    compact = sdk_contract.build_surface_contract(fresh_contract, fresh_ledger)
    # Stable rows retain their original compiler selector. Source keys are
    # rebound by prepare_ledger only after the final clean source matches.
    previous = {row["id"]: row for row in original["declarations"]}
    merged = []
    for row in fresh_contract["declarations"]:
        prior = previous.get(row["id"])
        if (
            prior is not None
            and prior["signatureSha256"] == row["signatureSha256"]
            and prior["classification"] == row["classification"]
            and prior["mapping"].get("ledgerMappingSha256")
            == row["mapping"].get("ledgerMappingSha256")
        ):
            retained = copy.deepcopy(prior)
            retained["mapping"]["pythonTargetSha256"] = row["mapping"][
                "pythonTargetSha256"
            ]
            merged.append(retained)
        else:
            merged.append(row)
    fresh_contract["declarations"] = merged
    if (
        stored_contract.get("surfaceContract") != "surface-contract.json"
        or stored_ledger.get("surfaceContract") != "surface-contract.json"
    ):
        raise ValueError("refresh requires the existing compact Surface include")
    contract_output = {
        **fresh_contract,
        "declarations": [
            row for row in merged if not sdk_contract._surface_path(row["rustPath"])
        ],
        "surfaceContract": "surface-contract.json",
    }
    raw_entries = copy.deepcopy(stored_ledger["entries"])
    network_paths = {
        "yosoi::DocumentProfile::network_observation_v1",
        "yosoi::documents::DocumentSchemaProfile::YosoiNetworkObservationV1",
    }
    raw_entries = [row for row in raw_entries if row["rustPath"] not in network_paths]
    known = {
        (
            row["rustPath"],
            sdk_contract._ledger_trait(row),
            sdk_contract._ledger_kind(row),
        )
        for row in raw_entries
    }
    for row in fresh_ledger["entries"]:
        if (
            not sdk_contract._surface_path(row["rustPath"])
            and (
                row["rustPath"],
                sdk_contract._ledger_trait(row),
                sdk_contract._ledger_kind(row),
            )
            not in known
        ):
            raw_entries.append(row)
    ledger_output = {
        **stored_ledger,
        "sourcePin": fresh_ledger["sourcePin"],
        "pythonPin": fresh_ledger["pythonPin"],
        "entries": raw_entries,
        "surfaceContract": "surface-contract.json",
    }
    if args.write:
        for path, value in (
            (args.ledger, ledger_output),
            (args.contract, contract_output),
            (args.contract.with_name("surface-contract.json"), compact),
        ):
            path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        loaded = sdk_contract.load_contract(args.contract)
        runtime, drift = sdk_contract.prepare_ledger(
            loaded, rust, python, parity.load_ledger(args.ledger)
        )
        if drift:
            raise ValueError(
                "saved refreshed contract has structural drift: " + json.dumps(drift)
            )
        parity.build_report(rust, python, runtime)
    print(
        json.dumps(
            {
                "source": rust["sourceRevision"],
                "pythonSurfaceDigest": python["surfaceDigest"],
                "scopedDeclarations": len(merged),
                "surfaceDeclarations": len(compact["declarations"]),
                "counts": report["coverage"]["counts"],
                "written": args.write,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
