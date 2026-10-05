"""Execute independent public Rust/Python workflows and retain raw comparisons."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def tooling() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sdk_parity", Path(__file__).with_name("parity.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load parity tooling")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from pydantic import create_model

    import yosoi as ys

    cases: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    policies = [("default-policy", ys.Policy()), ("bounded-policy", ys.Policy())]
    policies[1][1].request.maximum_elapsed = 5_000_000
    policies[1][1].documents.max_nodes = 1000
    for name, policy in policies:
        cases.append(
            {
                "kind": "policy",
                "name": name,
                "policy": None
                if name == "default-policy"
                else json.loads(policy.to_json()),
            }
        )
        expected.append(
            {
                "name": name,
                "result": {
                    "policy": json.loads(policy.to_json()),
                    "effective": policy.effective_policy().model_dump(
                        mode="json", exclude_none=True
                    ),
                    "snapshot": policy.snapshot().model_dump(
                        mode="json", exclude_none=True
                    ),
                },
            }
        )

    document_specs = [
        ("html-css", ys.Document.html, "<h1>Hello</h1>", ys.css("h1").text()),
        ("html-xpath", ys.Document.html, "<h1>Hello</h1>", ys.xpath("//h1").text()),
        (
            "html-tree-text",
            ys.Document.html,
            "<p>Hello</p>",
            ys.tree_text_contains("Hello").text(),
        ),
        (
            "xml-ns",
            ys.Document.xml,
            '<r xmlns="urn:test"><name>Hello</name></r>',
            ys.xpath("//t:name").with_namespace("t", "urn:test").text(),
        ),
        (
            "json-pointer",
            ys.Document.from_json,
            '{"name":"Hello"}',
            ys.json_pointer("/name").value(),
        ),
        (
            "json-path",
            ys.Document.from_json,
            '{"name":"Hello"}',
            ys.json_path("$.name").value(),
        ),
        (
            "text-literal",
            ys.Document.text,
            "Hello world",
            ys.text_literal("Hello").text(),
        ),
        (
            "text-regex",
            ys.Document.text,
            "Hello world",
            ys.regex("(?P<word>Hello)").captures("word"),
        ),
        (
            "html-attribute",
            ys.Document.html,
            '<a href="/next">Hello</a>',
            ys.css("a").attribute("href"),
        ),
        ("html-node", ys.Document.html, "<h1>Hello</h1>", ys.css("h1").node()),
        ("html-no-match", ys.Document.html, "<p>Missing</p>", ys.css("h1").text()),
        ("json-failed", ys.Document.from_json, "{", ys.json_pointer("").value()),
    ]
    fixtures = (
        Path(__file__).resolve().parents[2]
        / "benchmarks/fixtures/document-locators/v1/golden"
    )
    dom = (fixtures / "rendered-dom.json").read_text()
    accessibility = (fixtures / "accessibility-tree.json").read_text()
    document_specs.extend(
        [
            (
                "dom-css",
                lambda name, content: ys.Document.rendered_dom(name, 1, content),
                dom,
                ys.css("span").text(),
            ),
            (
                "ax-role",
                lambda name, content: ys.Document.accessibility_tree(name, 1, content),
                accessibility,
                ys.role("button").node(),
            ),
            (
                "ax-name",
                lambda name, content: ys.Document.accessibility_tree(name, 1, content),
                accessibility,
                ys.accessible_name("Buy now").name(),
            ),
            (
                "ax-text",
                lambda name, content: ys.Document.accessibility_tree(name, 1, content),
                accessibility,
                ys.accessibility_text("Buy now").text(),
            ),
            (
                "ax-state",
                lambda name, content: ys.Document.accessibility_tree(name, 1, content),
                accessibility,
                ys.accessibility_state("expanded", True).node(),
            ),
        ]
    )
    for name, constructor, content, locator in document_specs:
        document = constructor(name, content)
        plan = ys.Plan(outputs=[ys.output("value", locator)])
        cases.append(
            {
                "kind": "document",
                "name": name,
                "content": content,
                "profile": document.profile.model_dump(mode="json"),
                "plan": plan.compiled(),
            }
        )
        expected.append(
            {
                "name": name,
                "result": {
                    "profile": document.profile.model_dump(mode="json"),
                    "class": document.document_class,
                    "byte_len": document.byte_len,
                    "plan": plan.compiled(),
                    "located": document.locate(plan).model_dump(mode="json"),
                },
            }
        )

    contract_specs = [
        (
            "contract-valid",
            (
                "<article><b class=author>Ada</b><b class=price>$12.34</b>"
                "<i class=tag>a</i><i class=tag>b</i></article>"
            ),
        ),
        ("contract-empty-root", "<article></article>"),
        (
            "contract-negative-money",
            "<article><b class=author>Ada</b><b class=price>$-1.00</b></article>",
        ),
        (
            "contract-bad-money",
            "<article><b class=author>Ada</b><b class=price>free</b></article>",
        ),
        (
            "contract-excess",
            (
                "<article><b class=author>Ada</b><b class=author>Grace</b>"
                "<b class=price>$1.00</b></article>"
            ),
        ),
        ("contract-no-match", "<p>No rows</p>"),
    ]
    contract = create_model(
        "ConformanceBook",
        __base__=ys.Contract,
        author=(str, ys.Field("Author", id="byline", locator=ys.css(".author"))),
        price=(ys.Money, ys.Field("Price", locator=ys.css(".price"))),
        link=(
            str | None,
            ys.Field("Link", locator=ys.css("a").attribute("href"), default=None),
        ),
        tags=(list[str], ys.Field("Tags", locator=ys.css(".tag"))),
    )
    contract.root = ys.css("article")
    field_map = {"byline": "author", "price": "price", "link": "link", "tags": "tags"}
    for name, content in contract_specs:
        document = ys.Document.html(name, content)
        plan = contract.plan()
        located = document.locate(plan)
        extracted = ys.extract(document, contract)
        outcome = extracted.validate()
        wire = outcome.model_dump()
        try:
            records = outcome.require_all()
            # Check actual Python record values, while retaining native provenance.
            assert len(records) == len(outcome.records)
            required = {"records": wire.get("records", [])}
        except ys.contracts.ContractIssues as error:
            required = {"error": error.detail}
        typed_values = []
        for record in outcome.records:
            values = {}
            for field_id, attribute in field_map.items():
                value = getattr(record.value, attribute)
                values[field_id] = (
                    value.model_dump(mode="json")
                    if isinstance(value, ys.Money)
                    else value
                )
            typed_values.append(values)
        cases.append(
            {
                "kind": "contract",
                "name": name,
                "content": content,
                "profile": document.profile.model_dump(mode="json"),
                "plan": plan.compiled(),
                "schema": contract.contract_schema().model_dump(mode="json"),
            }
        )
        expected.append(
            {
                "name": name,
                "result": {
                    "profile": document.profile.model_dump(mode="json"),
                    "class": document.document_class,
                    "byte_len": document.byte_len,
                    "plan": plan.compiled(),
                    "located": located.model_dump(mode="json"),
                    "identity": contract.identity(),
                    "extracted": extracted.model_dump(),
                    "outcome": wire,
                    "required": required,
                    "typed_values": typed_values,
                },
            }
        )
    return cases, expected


def equivalent(value: Any) -> Any:
    """Normalize omitted nullable fields shared by Rust serde/Pydantic views.

    Cardinality value:null is retained; it describes an absent optional value.
    """
    if isinstance(value, dict):
        return {
            key: equivalent(item)
            for key, item in value.items()
            if item is not None or key == "value"
        }
    if isinstance(value, (list, tuple)):
        return [equivalent(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument("--rust-executable", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    module = tooling()
    rust = module.load_rust_inventory(args.rust_reference)
    python = module.introspect_python_package()
    inputs, expected = prepare_cases()
    process = subprocess.run(
        [str(args.rust_executable.resolve())],
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    actual = json.loads(process.stdout)
    if len(actual) != len(expected):
        raise RuntimeError("Rust/Python case count differs")
    raw_comparisons = []
    for rust_case, python_case in zip(actual, expected, strict=True):
        left, right = equivalent(rust_case), equivalent(python_case)
        raw_comparisons.append(
            {
                "name": python_case["name"],
                "rust": rust_case,
                "python": python_case,
                "equal": left == right,
                "rustSha256": module.digest_json(left),
                "pythonSha256": module.digest_json(right),
            }
        )
    passed = all(item["equal"] for item in raw_comparisons)
    # Raw workflows are retained independently of ledger claims. Per-symbol
    # verification is added only after reviewing which operation/argument each
    # fixture actually exercises; no blanket attribution to every Rust symbol.
    source = {
        key: rust[key]
        for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
    }
    python_identity = {
        key: python[key] for key in ("surfaceDigest", "implementationDigest", "runtime")
    }
    run_id = str(uuid.uuid4())
    ledger = module.load_ledger(args.ledger)
    # Explicit attribution to operations called by both implementations above.
    # Other symbols remain unverified until their own cases are executed.
    operations = {
        "yosoi::documents::Document::from_profile": "document",
        "yosoi::documents::Document::class": "document",
        "yosoi::documents::Document::byte_len": "document",
        "yosoi::documents::Document::locate": "document",
        "yosoi::policy::Policy::effective_policy": "policy",
        "yosoi::policy::PolicySnapshot::from_policy": "policy",
        "yosoi::policy::PolicySnapshot::policy": "policy",
        "yosoi::policy::PolicySnapshot::effective_policy": "policy",
        "yosoi::policy::PolicySnapshot::identity": "policy",
    }
    cases = []
    workflow_by_kind = {
        kind: [
            item
            for item, given in zip(raw_comparisons, inputs, strict=True)
            if given["kind"] == kind
        ]
        for kind in ("policy", "document", "contract")
    }
    for entry in ledger["entries"]:
        kind = operations.get(entry["rustPath"])
        if kind is None or entry.get("decision") != "mapped":
            continue
        selected = workflow_by_kind[kind]
        comparisons = [
            {
                "name": item["name"],
                "rustSha256": item["rustSha256"],
                "pythonSha256": item["pythonSha256"],
                "equal": item["equal"],
            }
            for item in selected
        ]
        # Each check is backed by the same varied, fully retained workflow outputs;
        # names identify the mapping under review, rather than invented passing tests.
        mapping_checks = []
        for mapping_kind, field, key_name in (
            ("argument", "argumentMappings", "rustArgument"),
            ("default", "defaults", "id"),
            ("unit", "units", "id"),
            ("cardinality", "cardinality", "id"),
        ):
            for mapping in entry.get(field, []):
                left = module.digest_json(
                    [equivalent(item["rust"]) for item in selected]
                )
                right = module.digest_json(
                    [equivalent(item["python"]) for item in selected]
                )
                mapping_checks.append(
                    {
                        "kind": mapping_kind,
                        "key": mapping[key_name],
                        "rustSha256": left,
                        "pythonSha256": right,
                        "equal": left == right,
                    }
                )
        case = {
            "testId": "public-workflows:" + entry["rustPath"],
            "rustPath": entry["rustPath"],
            "pythonTarget": entry["pythonTarget"],
            "outcome": "passed"
            if all(item["equal"] for item in selected)
            else "failed",
            "comparisons": comparisons,
            "mappingChecks": mapping_checks,
        }
        for key in ("symbolKey", "trait"):
            if entry.get(key):
                case[key] = entry[key]
        cases.append(case)
    result = {
        "schemaVersion": 1,
        "kind": "yosoi-python-rust-conformance-results",
        "runId": run_id,
        "outcome": "passed" if passed else "failed",
        "source": source,
        "python": python_identity,
        "cases": cases,
        "workflows": raw_comparisons,
        "inputs": inputs,
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
            "sha256": module.digest_bytes(raw_path.read_bytes()),
        },
    )
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "workflows": len(raw_comparisons),
                "passed": sum(item["equal"] for item in raw_comparisons),
                "outcome": result["outcome"],
                "evidence": str(args.output),
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
