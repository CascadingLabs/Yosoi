"""Refresh explicit video mappings against completed compiler IR and an installed wheel.

Existing source-matched reviews remain intact. Only genuinely new video APIs are
seeded; an unexplained signature change or absent counterpart stops the refresh.
No behavioral evidence is created, and all existing SDK suites remain required.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import sdk_contract
from refresh_image_contract import refresh as _image_refresh
from run_sdk_parity import _assert_installed_package
from video_surface_mappings import video_mapping

import parity


def refresh(
    rust: dict[str, Any], python: dict[str, Any], ledger: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Add explicit new video entries before the unchanged full semantic checks."""
    seeded = copy.deepcopy(ledger)
    for item in rust["items"]:
        if sdk_contract._expected_classification(item) != "sdk":
            continue
        candidates = [
            row
            for row in ledger["entries"]
            if row["rustPath"] == item["rustPath"]
            and sdk_contract._ledger_trait(row) == item.get("trait")
            and sdk_contract._ledger_kind(row) in {None, item["kind"]}
        ]
        if candidates:
            if not any(
                row.get("symbolKey") == item["symbolKey"]
                or sdk_contract._ledger_signature_digest(row)
                == sdk_contract._digest_text(item.get("signature") or "")
                for row in candidates
            ):
                raise ValueError(
                    "video refresh refuses an unreviewed signature change: "
                    + item["rustPath"]
                )
            continue
        entry = video_mapping(item, python)
        if entry is not None:
            seeded["entries"].append(entry)
    return _image_refresh(rust, python, seeded)


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
