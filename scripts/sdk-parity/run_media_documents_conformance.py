"""Compare Rust-authored media values and failures with the installed Python SDK.

Build with ``cargo build -p yosoi --example media_documents_conformance``.
The Rust example authors every payload and bound; this runner reconstructs those
inputs through Python's public API and records digest-bound comparisons.
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

from media_documents_conformance import (
    EVIDENCE_KIND,
    FILE_DOCUMENT_PATH,
    FILE_LIMITS_PATH,
    FILE_METADATA_PATH,
    RESULT_KIND,
    _plain,
    evidence_cases,
    validate_fixture_set,
)
from media_documents_runtime import (
    compare_document_case,
    compare_error_case,
    observe_document,
    observe_error,
)

import parity


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
    python_inventory = parity.introspect_python_package(python_root=args.python_root)
    process = subprocess.run(
        [str(args.rust_executable.resolve())],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    (
        cases,
        error_cases,
        standalone_rust,
        equality_rust,
        rust_file_limits,
    ) = validate_fixture_set(json.loads(process.stdout))
    python_root = str(args.python_root.resolve())
    if python_root not in sys.path:
        sys.path.insert(0, python_root)
    ys = importlib.import_module("yosoi")
    ledger = parity.load_ledger(args.ledger)

    comparisons = [
        compare_document_case(case, observe_document(case, ys), parity)
        for case in cases
    ]
    for case in error_cases:
        observed, exception_type = observe_error(case, ys)
        comparisons.append(compare_error_case(case, observed, exception_type))

    standalone = ys.FileMetadata()
    standalone_python = _plain(standalone.model_dump())
    standalone_python["probe_validated_video_container"] = (
        standalone.probe_validated_video_container
    )
    standalone_equal = (
        standalone_python == standalone_rust and standalone.sha256 is None
    )
    standalone_comparison = {
        "name": "standalone-metadata-sha256",
        "rustPath": FILE_METADATA_PATH,
        "evidenceRustPaths": [
            FILE_METADATA_PATH,
            f"{FILE_METADATA_PATH}::sha256",
        ],
        "rust": standalone_rust,
        "python": standalone_python,
        "comparisons": [
            {
                "name": "standalone-metadata:fields",
                "rustSha256": parity.digest_json(standalone_rust),
                "pythonSha256": parity.digest_json(standalone_python),
                "equal": standalone_python == standalone_rust,
            },
            {
                "name": "standalone-metadata:sha256",
                "rustSha256": parity.digest_json(None),
                "pythonSha256": parity.digest_json(standalone.sha256),
                "equal": standalone.sha256 is None,
            },
        ],
        "mappingValuesByPath": {
            f"{FILE_METADATA_PATH}::sha256": {
                "rust": {"sha256": standalone_rust["sha256"]},
                "python": {"sha256": standalone.sha256},
            }
        },
        "equal": standalone_equal,
        "rustSha256": parity.digest_json(standalone_rust),
        "pythonSha256": parity.digest_json(standalone_python),
    }
    comparisons.append(standalone_comparison)

    png = bytes(next(case for case in cases if case["name"] == "png")["input"]["bytes"])
    left = ys.ImageDocument.from_bytes("same-image", png, limits=ys.FileLimits())
    right = ys.ImageDocument.from_bytes(
        "same-image", png, limits=ys.FileLimits(max_bytes=len(png))
    )
    different = ys.ImageDocument.from_bytes("other-image", png)
    equality_python = {
        "same_value_different_handles_and_limits": left == right,
        "different_identity": left == different,
    }
    equality_comparison = {
        "name": "value-equality",
        "rustPath": FILE_DOCUMENT_PATH,
        "evidenceRustPaths": [FILE_DOCUMENT_PATH],
        "rust": equality_rust,
        "python": equality_python,
        "comparisons": [
            {
                "name": f"value-equality:{field}",
                "rustSha256": parity.digest_json(value),
                "pythonSha256": parity.digest_json(equality_python[field]),
                "equal": equality_python[field] == value,
            }
            for field, value in equality_rust.items()
        ],
        "equal": equality_python == equality_rust,
        "rustSha256": parity.digest_json(equality_rust),
        "pythonSha256": parity.digest_json(equality_python),
    }
    comparisons.append(equality_comparison)

    media_module = importlib.import_module("yosoi.media")
    python_file_limits = {
        "defaultMaxBytes": ys.FileLimits().max_bytes,
        "hardMaxBytes": media_module.MAX_FILE_LIMIT_BYTES,
        "sourceMaxBytes": ys.MAX_SOURCE_BYTES,
    }
    limit_comparisons = [
        {
            "name": f"file-limits:{field}",
            "rustSha256": parity.digest_json(rust_file_limits[field]),
            "pythonSha256": parity.digest_json(python_file_limits[field]),
            "equal": rust_file_limits[field] == python_file_limits[field],
        }
        for field in (
            "defaultMaxBytes",
            "hardMaxBytes",
            "sourceMaxBytes",
        )
    ]
    comparisons.append(
        {
            "name": "file-limits-and-constants",
            "rustPath": f"{FILE_LIMITS_PATH}::max_bytes",
            "evidenceRustPaths": [
                FILE_LIMITS_PATH,
                f"{FILE_LIMITS_PATH}::max_bytes",
                "yosoi::documents::DEFAULT_FILE_MAX_BYTES",
                "yosoi::documents::MAX_FILE_BYTES",
                "yosoi::documents::MAX_SOURCE_BYTES",
            ],
            "rust": rust_file_limits,
            "python": python_file_limits,
            "comparisons": limit_comparisons,
            "equal": all(item["equal"] for item in limit_comparisons),
            "rustSha256": parity.digest_json(rust_file_limits),
            "pythonSha256": parity.digest_json(python_file_limits),
        }
    )

    fixture_cases = evidence_cases(comparisons, rust, ledger)
    passed = all(item["equal"] for item in comparisons)
    source = {
        key: rust[key]
        for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
    }
    identity = {
        key: python_inventory[key]
        for key in ("surfaceDigest", "implementationDigest", "runtime")
    }
    run_id = str(uuid.uuid4())
    result = {
        "schemaVersion": 1,
        "kind": RESULT_KIND,
        "runId": run_id,
        "outcome": "passed" if passed else "failed",
        "source": source,
        "python": identity,
        "cases": fixture_cases,
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
        kind=EVIDENCE_KIND,
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
                "attributions": len(fixture_cases),
                "outcome": result["outcome"],
                "evidence": str(args.output),
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
