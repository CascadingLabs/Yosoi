"""Compare Rust-authored actual image observations with the installed wheel."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from image_surface_conformance import (
    EVIDENCE_KIND,
    RESULT_KIND,
    evidence_cases,
    validate_fixture_set,
)
from image_surface_runtime import observe_fixtures

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
    fixtures = validate_fixture_set(json.loads(process.stdout))
    python_root = str(args.python_root.resolve())
    if python_root not in sys.path:
        sys.path.insert(0, python_root)
    ys = importlib.import_module("yosoi")
    comparisons = observe_fixtures(fixtures, ys)
    cases = evidence_cases(comparisons, rust, parity.load_ledger(args.ledger))
    passed = all(row["equal"] for row in comparisons) and all(
        row["outcome"] == "passed" for row in cases
    )
    result = {
        "schemaVersion": 1,
        "kind": RESULT_KIND,
        "runId": str(uuid.uuid4()),
        "outcome": "passed" if passed else "failed",
        "source": {
            key: rust[key]
            for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
        },
        "python": {
            key: python_inventory[key]
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
    raw = args.output.with_name(args.output.stem + "-results.json")
    raw.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    evidence = {
        key: result[key]
        for key in ("schemaVersion", "runId", "outcome", "source", "python", "cases")
    }
    evidence.update(
        kind=EVIDENCE_KIND,
        executedAt=datetime.now(UTC).isoformat(),
        runner={"command": [sys.executable, *sys.argv]},
        resultArtifact={
            "path": raw.name,
            "sha256": parity.digest_bytes(raw.read_bytes()),
        },
    )
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "fixtures": len(comparisons),
                "matched": sum(row["equal"] for row in comparisons),
                "attributions": len(cases),
                "outcome": result["outcome"],
                "evidence": str(args.output),
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
