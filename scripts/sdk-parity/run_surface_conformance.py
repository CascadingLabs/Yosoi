"""Compare installed Python Surface results with the public Rust SDK example."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import parity


def load_vectors(path: Path) -> list[dict[str, str]]:
    """Require the six agreed document representations before comparing SDKs."""
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Surface vectors must be a JSON object")
    expected = {"html", "xml", "json", "text", "rendered_dom", "accessibility_tree"}
    cases = value.get("cases")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1:
        raise ValueError("unsupported Surface vector schema")
    if not isinstance(cases, list) or len(cases) != len(expected):
        raise ValueError("Surface vectors must cover all six document representations")
    for case in cases:
        if not isinstance(case, dict) or any(
            not isinstance(case.get(field), str) or not case[field]
            for field in ("name", "format", "content", "query")
        ):
            raise ValueError("Surface vector fields must be nonempty strings")
    if {case["format"] for case in cases} != expected or len(
        {case["name"] for case in cases}
    ) != len(cases):
        raise ValueError("Surface vectors must have unique names and formats")
    return cases


def main() -> None:
    import yosoi as ys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-binary", "--rust-executable", type=Path, required=True)
    parser.add_argument(
        "--vectors",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "python/parity/surface-vectors.json",
    )
    parser.add_argument("--out", "--output", type=Path, required=True)
    parser.add_argument("--rust-reference", type=Path)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    args = parser.parse_args()
    vectors = load_vectors(args.vectors)
    rust = json.loads(
        subprocess.check_output([str(args.rust_binary), str(args.vectors)], timeout=30)
    )
    python = []
    constructors = {
        "html": ys.Document.html,
        "xml": ys.Document.xml,
        "json": ys.Document.from_json,
        "text": ys.Document.text,
        "rendered_dom": lambda name, content: ys.Document.rendered_dom(
            name, 7, content
        ),
        "accessibility_tree": lambda name, content: ys.Document.accessibility_tree(
            name, 7, content
        ),
    }
    for case in vectors:
        index = ys.Surface(constructors[case["format"]](case["name"], case["content"]))
        found = index.find(case["query"])
        python.append(
            {
                "name": case["name"],
                "metadata": index.metadata.model_dump(mode="json"),
                "overview": index.overview().model_dump(mode="json"),
                "found": found.model_dump(mode="json"),
                "details": [
                    index.inspect(entry.reference).model_dump(mode="json")
                    for entry in found.entries
                ],
            }
        )
    if python != rust:
        raise RuntimeError("Rust/Python Surface evidence differs")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "passed": True,
                "cases": len(python),
                "package": ys.__version__,
                "native": ys._native.__file__,
                "values": python,
            },
            indent=2,
        )
    )
    if args.rust_reference is not None:
        write_evidence(args, rust, python)
    print(json.dumps({"passed": True, "cases": len(python), "evidence": str(args.out)}))


def write_evidence(
    args: argparse.Namespace, rust_values: list, python_values: list
) -> None:
    """Attribute only operations exercised by both sides of the shared vectors."""
    rust = parity.load_rust_inventory(args.rust_reference)
    python = parity.introspect_python_package()
    ledger = parity.load_ledger(args.ledger)
    source = {
        name: rust[name]
        for name in ("sourceRevision", "inventorySignature", "featureProfileDigest")
    }
    identity = {
        name: python[name]
        for name in ("surfaceDigest", "implementationDigest", "runtime")
    }
    compared = [
        {
            "name": left["name"],
            "rustSha256": parity.digest_json(left),
            "pythonSha256": parity.digest_json(right),
            "equal": left == right,
        }
        for left, right in zip(rust_values, python_values, strict=True)
    ]
    methods = {
        "new",
        "with_limits",
        "identity",
        "representation",
        "source_bytes",
        "node_count",
        "coverage",
        "root",
        "overview",
        "find",
        "inspect",
    }
    cases = []
    for entry in ledger["entries"]:
        path = entry["rustPath"]
        if (
            not path.startswith("yosoi::Surface::")
            or path.rsplit("::", 1)[-1] not in methods
            or entry.get("trait") is not None
            or entry.get("decision") != "mapped"
        ):
            continue
        checks = []
        left = parity.digest_json(rust_values)
        right = parity.digest_json(python_values)
        for mapping in entry.get("argumentMappings", []):
            checks.append(
                {
                    "kind": "argument",
                    "key": mapping["rustArgument"],
                    "rustSha256": left,
                    "pythonSha256": right,
                    "equal": left == right,
                }
            )
        cases.append(
            {
                "testId": "surface-vectors:" + path,
                "rustPath": path,
                "symbolKey": entry.get("symbolKey"),
                "pythonTarget": entry["pythonTarget"],
                "outcome": "passed",
                "comparisons": compared,
                "mappingChecks": checks,
            }
        )
    if not cases:
        raise ValueError("Surface conformance has no reviewed operation mappings")
    result = {
        "schemaVersion": 1,
        "kind": "yosoi-python-rust-conformance-results",
        "runId": str(uuid.uuid4()),
        "outcome": "passed",
        "source": source,
        "python": identity,
        "cases": cases,
        "rustValues": rust_values,
        "pythonValues": python_values,
    }
    raw = args.out.with_name(args.out.stem + "-results.json")
    raw.write_text(json.dumps(result, indent=2))
    evidence = {
        key: result[key]
        for key in ("schemaVersion", "runId", "outcome", "source", "python", "cases")
    }
    evidence.update(
        kind="yosoi-python-rust-conformance",
        executedAt=datetime.now(UTC).isoformat(),
        runner={"command": [sys.executable, *sys.argv]},
        resultArtifact={
            "path": raw.name,
            "sha256": parity.digest_bytes(raw.read_bytes()),
        },
    )
    args.out.write_text(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
