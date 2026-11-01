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
from typing import Any, ClassVar


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
    from pydantic import BaseModel, ValidationError, create_model

    import yosoi as ys
    from yosoi.errors import rust_error_details

    cases: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []

    media_fixtures = (
        ("image", b"\x89PNG\r\n\x1a\nfixture image", ys.ImageDocument),
        ("video", b"\x00\x00\x00\x10ftypmp42", ys.VideoDocument),
        ("audio", b"ID3\x04\x00\x00\x00\x00\x00\x00", ys.AudioDocument),
        ("binary", b"opaque binary payload", ys.BinaryDocument),
    )

    def file_metadata(kind: str) -> ys.FileMetadata:
        return (
            ys.FileMetadata()
            .with_filename(f"fixture.{kind}")
            .with_declared_media_type("application/octet-stream")
            .with_source("sdk-parity")
            .with_capture_id(f"capture-{kind}")
            .with_session_id("session-sdk-parity")
            .with_tab_id("tab-sdk-parity")
            .with_download_id(f"download-{kind}")
        )

    def file_value(document: Any, maximum_bytes: int) -> dict[str, Any]:
        kind_by_type = {
            ys.ImageDocument: "image",
            ys.VideoDocument: "video",
            ys.AudioDocument: "audio",
            ys.BinaryDocument: "binary",
        }
        kind = kind_by_type.get(type(document))
        if kind is None:
            raise TypeError(f"unexpected file document type: {type(document).__name__}")
        return {
            "id": str(document.id),
            "kind": kind,
            "bytes": list(document.bytes),
            "byte_len": document.byte_len,
            "sha256": document.sha256,
            "metadata": document.metadata.model_dump(mode="json"),
            "maximum_bytes": maximum_bytes,
            "default_file_max_bytes": ys.documents.DEFAULT_FILE_MAX_BYTES,
            "max_file_bytes": ys.documents.MAX_FILE_BYTES,
            "max_recording_duration_ms": ys.policy.MAX_RECORDING_DURATION_MS,
        }

    from yosoi.contracts import value_type_id

    file_limit_value = ys.FileLimits(max_bytes=731)
    cases.append(
        {"kind": "file_limits", "name": "file-limits-max-bytes", "max_bytes": 731}
    )
    expected.append(
        {
            "name": "file-limits-max-bytes",
            "result": {"max_bytes": file_limit_value.max_bytes},
        }
    )

    class CustomValue:
        TYPE_ID: ClassVar[str] = "custom.review"

    class EmptyIdentity:
        TYPE_ID: ClassVar[str] = ""

    cases.append(
        {"kind": "contract_value_identity", "name": "contract-value-identities"}
    )
    expected.append(
        {
            "name": "contract-value-identities",
            "result": {
                "string": value_type_id(str),
                "custom": value_type_id(CustomValue),
                "empty": value_type_id(EmptyIdentity),
            },
        }
    )
    from yosoi.contracts import (
        RuntimeExactlyOne,
        RuntimeMany,
        RuntimeString,
        RuntimeZeroOrOne,
    )
    from yosoi.locators import QueryAtom, QuerySpec, TreeCoordinate

    for name, value in (
        ("tree-required-null", TreeCoordinate.try_new((1,))),
        (
            "query-absent-namespaces",
            QuerySpec.new(QueryAtom(kind="css", value="article"), "tree_nodes"),
        ),
        (
            "query-present-namespaces",
            QuerySpec.new(
                QueryAtom(kind="x_path", value="//p:name"), "tree_nodes"
            ).with_namespace("p", "urn:test"),
        ),
        ("map-unit-termination", ys.map.MapTermination(kind="exhausted")),
        (
            "runtime-optional-null",
            RuntimeZeroOrOne(cardinality="zero_or_one", value=None),
        ),
    ):
        cases.append({"kind": "wire_view", "name": name})
        expected.append(
            {"name": name, "result": {"value": value.model_dump(mode="json")}}
        )
    for rust_type, model in (
        ("yosoi::Policy", ys.Policy),
        ("yosoi::policy::Map", ys.policy.Map),
        ("yosoi::policy::Filters", ys.policy.Filters),
    ):
        name = "clone-model:" + rust_type
        original = model()
        cloned = original.clone()
        filters = (
            cloned.map.filters
            if isinstance(cloned, ys.Policy)
            else (cloned.filters if isinstance(cloned, ys.policy.Map) else cloned)
        )
        filters.excluded_query_keys.append("clone-only")

        def serialize(value: Any) -> Any:
            return (
                json.loads(value.to_json())
                if isinstance(value, ys.Policy)
                else value.model_dump(mode="json")
            )

        cases.append(
            {
                "kind": "model_clone",
                "name": name,
                "rust_type": rust_type,
                "marker": "clone-only",
            }
        )
        expected.append(
            {
                "name": name,
                "result": {"original": serialize(original), "clone": serialize(cloned)},
            }
        )
    # Compare actual public Rust Default implementations with Python authoring
    # defaults, rather than feeding Python-created values back to Rust.
    default_models = [
        ("yosoi::Policy", ys.Policy),
        ("yosoi::policy::Page", ys.policy.Page),
        ("yosoi::policy::Request", ys.policy.Request),
        ("yosoi::policy::SourceLimits", ys.policy.SourceLimits),
        ("yosoi::policy::BrowserLimits", ys.policy.BrowserLimits),
        ("yosoi::policy::DirectHttpRedirects", ys.policy.Redirects.default),
        ("yosoi::policy::Documents", ys.policy.Documents),
        ("yosoi::policy::Locators", ys.policy.Locators),
        ("yosoi::policy::Map", ys.policy.Map),
        ("yosoi::policy::Limits", ys.policy.MapLimits),
        ("yosoi::policy::Filters", ys.policy.Filters),
        ("yosoi::policy::Scope", ys.policy.Scope),
        ("yosoi::policy::Tuning", ys.policy.Tuning),
        ("yosoi::policy::search::Search", ys.policy.Search),
        ("yosoi::policy::EventLimit", ys.policy.EventLimit.default),
        ("yosoi::policy::MaximumElapsed", ys.policy.MaximumElapsed.default),
        ("yosoi::policy::RedirectHopLimit", ys.policy.RedirectHopLimit.default),
        ("yosoi::policy::ObserveLimits", ys.policy.ObserveLimits),
        ("yosoi::policy::ObservePolicy", ys.policy.ObservePolicy),
        ("yosoi::policy::RecordingRule", ys.policy.RecordingRule),
        ("yosoi::policy::ScreenshotPolicy", ys.policy.ScreenshotPolicy),
        ("yosoi::documents::FileLimits", ys.FileLimits),
        ("yosoi::documents::FileMetadata", ys.FileMetadata),
        ("yosoi::map::Summary", ys.map.Summary),
        ("yosoi::search::SearchHitMetadata", ys.search.SearchHitMetadata),
    ]
    for rust_type, model in default_models:
        name = "default-model:" + rust_type
        cases.append({"kind": "model_default", "name": name, "rust_type": rust_type})
        value = model()
        serialized = (
            json.loads(value.to_json())
            if isinstance(value, ys.Policy)
            else value.model_dump(
                mode="json",
                exclude_none=rust_type
                in {
                    "yosoi::policy::ObservePolicy",
                    "yosoi::policy::ScreenshotPolicy",
                },
            )
            if isinstance(value, BaseModel)
            else value
        )
        omitted_fields = (
            {"tuning": value.tuning.model_dump(mode="json")}
            if isinstance(value, ys.Policy)
            else {}
        )
        expected.append(
            {
                "name": name,
                "result": {"value": serialized, "omitted_fields": omitted_fields},
            }
        )
    # Exercise constructor arguments and result-shape preservation independently
    # from locating documents. Namespace error cases compare real Rust failures.
    query_inputs = [
        ("css", "article", "tree_nodes", "new", None, None),
        ("css", "article", "json_values", "new", None, None),
        ("css", "", "tree_nodes", "new", None, None),
        ("text_literal", "café", "text_ranges", "new", None, None),
        ("x_path", "//t:name", "tree_nodes", "with_namespace", "t", "urn:test"),
        ("css", "name", "tree_nodes", "with_default_namespace", None, "urn:test"),
        ("x_path", "//name", "tree_nodes", "with_default_namespace", None, "urn:test"),
        ("css", "name", "tree_nodes", "with_namespace", "xml", "urn:invalid"),
        ("css", "name", "tree_nodes", "with_namespace", "t", ""),
        ("json_pointer", "/name", "json_values", "with_namespace", "t", "urn:test"),
    ]
    for index, (atom_kind, value, shape, operation, prefix, uri) in enumerate(
        query_inputs
    ):
        name = f"query-{index}-{operation}"
        source = QuerySpec.new(QueryAtom(kind=atom_kind, value=value), shape)
        case = {
            "kind": "query",
            "name": name,
            "query": source.model_dump(mode="json"),
            "operation": operation,
            "prefix": prefix,
            "uri": uri,
        }
        try:
            if operation == "with_namespace":
                assert prefix is not None and uri is not None
                query = source.with_namespace(prefix, uri)
            elif operation == "with_default_namespace":
                assert uri is not None
                query = source.with_default_namespace(uri)
            else:
                query = QuerySpec.new(source.atom, source.result_shape)
            result = {
                "query": query.model_dump(mode="json", exclude_defaults=True),
                "atom": query.atom.model_dump(mode="json"),
                "result_shape": query.result_shape,
                "namespace_bindings": [
                    item.model_dump(mode="json") for item in query.namespace_bindings
                ],
                "query_bytes": query.query_bytes,
            }
            # Only nonempty authoring atoms can be converted to the ergonomic DSL.
            # QuerySpec itself intentionally preserves unchecked raw atoms.
            if value:
                assert query.to_query().compiled() == query
        except ys._native.LocatorError as error:
            result = {"error": str(error)}
        cases.append(case)
        expected.append({"name": name, "result": result})
    policies = [("default-policy", ys.Policy()), ("bounded-policy", ys.Policy())]
    policies[1][1].request.maximum_elapsed = 5_000_000
    policies[1][1].documents.max_nodes = 1000
    policies[1][1].observe = ys.policy.ObservePolicy(
        enabled=True,
        native_tab_capture=True,
        screenshots=ys.policy.ScreenshotPolicy(
            before="target", after="viewport", failure="target"
        ),
        recordings=[
            ys.policy.RecordingRule(mode="browser_visible"),
            ys.policy.RecordingRule(mode="each_tab", include_audio=True),
        ],
        limits=ys.policy.ObserveLimits(max_sources=4, max_recordings=2),
    )
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
                    "max_recording_duration_ms": ys.policy.MAX_RECORDING_DURATION_MS,
                },
            }
        )

    invalid_observe = ys.policy.ObservePolicy(
        enabled=True,
        native_tab_capture=True,
        recordings=[
            ys.policy.RecordingRule(mode="each_tab"),
            ys.policy.RecordingRule(mode="each_tab"),
        ],
        limits=ys.policy.ObserveLimits(max_recordings=1),
    )
    invalid_policy_value = {"observe": invalid_observe.model_dump(mode="json")}
    try:
        ys.Policy.model_validate(invalid_policy_value)
    except ValidationError as error:
        details = rust_error_details(error)
        if details is None:
            raise AssertionError(
                "observation limit error lacks native Rust details"
            ) from error
        policy_error = {
            "rust_type": details.rust_type,
            "variant": details.variant,
            "details": dict(details.details),
            "source_chain": list(details.source_chain),
        }
    else:
        raise AssertionError("too many recording rules unexpectedly passed validation")
    cases.append({"kind": "policy_error", "name": "observe-recording-rule-limit"})
    expected.append(
        {
            "name": "observe-recording-rule-limit",
            "result": {"error": policy_error},
        }
    )

    for family, payload, _document_type in media_fixtures:
        identifier = f"file-factory-{family}"
        maximum_bytes = 1024
        metadata = file_metadata(family)
        document = ys.file_from_bytes(
            identifier,
            payload,
            metadata=metadata,
            limits=ys.FileLimits(max_bytes=maximum_bytes),
        )
        cases.append(
            {
                "kind": "file_document",
                "name": identifier,
                "id": identifier,
                "bytes": list(payload),
                "metadata": metadata.model_dump(mode="json", exclude_none=True),
                "max_bytes": maximum_bytes,
            }
        )
        expected.append(
            {
                "name": identifier,
                "result": file_value(document, maximum_bytes),
            }
        )

        for constructor in ("default", "limits", "metadata"):
            identifier = f"file-typed-{family}-{constructor}"
            maximum_bytes = (
                ys.documents.DEFAULT_FILE_MAX_BYTES
                if constructor == "default"
                else 1024
            )
            metadata = (
                file_metadata(family)
                if constructor == "metadata"
                else ys.FileMetadata()
            )
            document = _document_type.from_bytes(
                identifier,
                payload,
                **(
                    {}
                    if constructor == "default"
                    else {"limits": ys.FileLimits(max_bytes=maximum_bytes)}
                    if constructor == "limits"
                    else {
                        "metadata": metadata,
                        "limits": ys.FileLimits(max_bytes=maximum_bytes),
                    }
                ),
            )
            cases.append(
                {
                    "kind": "typed_file_document",
                    "name": identifier,
                    "id": identifier,
                    "family": family,
                    "constructor": constructor,
                    "bytes": list(payload),
                    "metadata": metadata.model_dump(mode="json", exclude_none=True),
                    "max_bytes": maximum_bytes,
                }
            )
            expected.append(
                {
                    "name": identifier,
                    "result": file_value(document, maximum_bytes),
                }
            )

    boundary_id = "file-limit-at-bound"
    boundary_payload = b"x"
    boundary_limit = ys.FileLimits(max_bytes=len(boundary_payload))
    boundary_document = ys.file_from_bytes(
        boundary_id, boundary_payload, limits=boundary_limit
    )
    cases.append(
        {
            "kind": "file_document",
            "name": boundary_id,
            "id": boundary_id,
            "bytes": list(boundary_payload),
            "metadata": {},
            "max_bytes": boundary_limit.max_bytes,
        }
    )
    expected.append(
        {
            "name": boundary_id,
            "result": file_value(boundary_document, boundary_limit.max_bytes),
        }
    )

    too_large_id = "file-limit-one-byte-over"
    too_large_payload = b"xy"
    too_large_limit = ys.FileLimits(max_bytes=len(too_large_payload) - 1)
    cases.append(
        {
            "kind": "file_too_large_error",
            "name": too_large_id,
            "id": too_large_id,
            "bytes": list(too_large_payload),
            "max_bytes": too_large_limit.max_bytes,
        }
    )
    try:
        ys.file_from_bytes(too_large_id, too_large_payload, limits=too_large_limit)
    except ys.FileDocumentError as error:
        details = rust_error_details(error)
        if details is None:
            raise AssertionError("oversized file lacks native Rust details") from error
        too_large_error = {
            "rust_type": details.rust_type,
            "variant": details.variant,
            "details": dict(details.details),
            "source_chain": list(details.source_chain),
        }
    else:
        raise AssertionError("file above the configured limit unexpectedly passed")
    expected.append(
        {
            "name": too_large_id,
            "result": {"error": too_large_error},
        }
    )

    too_long_filename = "é" * 513
    cases.append(
        {
            "kind": "file_metadata_error",
            "name": "file-metadata-utf8-byte-limit",
            "filename": too_long_filename,
        }
    )
    try:
        ys.FileMetadata().with_filename(too_long_filename)
    except ys.FileDocumentError as error:
        details = rust_error_details(error)
        if details is None:
            raise AssertionError(
                "FileDocumentError lacks native Rust details"
            ) from error
        metadata_error = {
            "rust_type": details.rust_type,
            "variant": details.variant,
            "details": dict(details.details),
            "source_chain": list(details.source_chain),
        }
    else:
        raise AssertionError("oversized UTF-8 metadata unexpectedly passed validation")
    expected.append(
        {
            "name": "file-metadata-utf8-byte-limit",
            "result": {"error": metadata_error},
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
            "contract-negative-price-text",
            "<article><b class=author>Ada</b><b class=price>$-1.00</b></article>",
        ),
        (
            "contract-unparsed-price-text",
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
        price=(str, ys.Field("Price", locator=ys.css(".price"))),
        link=(
            str | None,
            ys.Field("Link", locator=ys.css("a").attribute("href"), default=None),
        ),
        tags=(list[str], ys.Field("Tags", locator=ys.css(".tag"))),
    )
    contract.root = ys.css("article")
    # This workflow asserts the shared Rust contract wire; Python business validation
    # is covered by Contract tests and intentionally follows Pydantic semantics.
    runtime_contract = ys.contracts.RuntimeContract.new(contract.contract_schema())
    field_ids = ("byline", "price", "link", "tags")

    def scalar(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, RuntimeString):
            return value.value
        raise TypeError(f"unsupported runtime scalar: {type(value).__name__}")

    for name, content in contract_specs:
        document = ys.Document.html(name, content)
        plan = contract.plan()
        located = document.locate(plan)
        extracted = runtime_contract.extract(located)
        outcome = extracted.validate()
        wire = outcome.model_dump()
        try:
            records = outcome.require_all()
            required = {
                "records": [record.model_dump(mode="json") for record in records]
            }
            # The public typed view fills absent schema fields. Keep the exact
            # public outcome wire as an independent comparison, without filtering.
            required_wire = {"records": wire.get("records", [])}
        except ys.contracts.ContractIssues as error:
            required = {"error": error.detail}
            required_wire = {"error": error.detail}
        typed_values = []
        for record in outcome.records:
            values = {}
            for field_id in field_ids:
                value = record.value[field_id]
                if isinstance(value, RuntimeExactlyOne):
                    values[field_id] = scalar(value.value)
                elif isinstance(value, RuntimeZeroOrOne):
                    values[field_id] = (
                        None if value.value is None else scalar(value.value)
                    )
                elif isinstance(value, RuntimeMany):
                    values[field_id] = [scalar(item) for item in value.values]
                else:
                    raise TypeError(
                        f"unsupported runtime field value: {type(value).__name__}"
                    )
            typed_values.append(values)
        cases.append(
            {
                "kind": "contract",
                "name": name,
                "content": content,
                "profile": document.profile.model_dump(mode="json"),
                "plan": plan.compiled(),
                "schema": runtime_contract.contract_schema.model_dump(mode="json"),
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
                    "identity": runtime_contract.identity(),
                    "extracted": extracted.model_dump(),
                    "outcome": wire,
                    "archived": outcome.to_archived().model_dump(),
                    "required": required,
                    "required_wire": required_wire,
                    "typed_values": typed_values,
                },
            }
        )
    return cases, expected


def equivalent(value: Any) -> Any:
    """Convert container wrappers while retaining every JSON value and key."""
    if isinstance(value, dict):
        return {key: equivalent(item) for key, item in value.items()}
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
        "yosoi::contracts::ContractValue": "contract_value_identity",
        "yosoi::contracts::ContractValue::TYPE_ID": "contract_value_identity",
        "yosoi::locators::QuerySpec::new": "query",
        "yosoi::locators::QuerySpec::atom": "query",
        "yosoi::locators::QuerySpec::result_shape": "query",
        "yosoi::locators::QuerySpec::namespace_bindings": "query",
        "yosoi::locators::QuerySpec::query_bytes": "query",
        "yosoi::locators::QuerySpec::with_namespace": "query",
        "yosoi::locators::QuerySpec::with_default_namespace": "query",
        "yosoi::contracts::ContractOutcome::to_archived": "contract",
        "yosoi::Document::from_profile": "document",
        "yosoi::Document::class": "document",
        "yosoi::Document::byte_len": "document",
        "yosoi::Document::locate": "document",
        "yosoi::Policy::effective_policy": "policy",
        "yosoi::documents::Document::from_profile": "document",
        "yosoi::documents::Document::class": "document",
        "yosoi::documents::Document::byte_len": "document",
        "yosoi::documents::Document::locate": "document",
        "yosoi::policy::Policy::effective_policy": "policy",
        "yosoi::policy::PolicySnapshot::from_policy": "policy",
        "yosoi::policy::PolicySnapshot::policy": "policy",
        "yosoi::policy::PolicySnapshot::effective_policy": "policy",
        "yosoi::policy::PolicySnapshot::identity": "policy",
        "yosoi::Policy::observe": "policy",
        "yosoi::policy::ObserveLimits": "policy",
        "yosoi::policy::ObservePolicy": "policy",
        "yosoi::policy::RecordingMode": "policy",
        "yosoi::policy::RecordingRule": "policy",
        "yosoi::policy::ScreenshotPolicy": "policy",
        "yosoi::policy::ScreenshotScope": "policy",
        "yosoi::policy::observe::MAX_RECORDING_DURATION_MS": "policy",
        "yosoi::PolicyError::ObservationRulesExceedRecordingLimit": "policy_error",
        "yosoi::documents::DEFAULT_FILE_MAX_BYTES": "file_document",
        "yosoi::documents::MAX_FILE_BYTES": "file_document",
        "yosoi::documents::FileDocument": "file_document",
        "yosoi::documents::FileDocument::id": "file_document",
        "yosoi::documents::FileDocument::metadata": "file_document",
        "yosoi::documents::FileDocument::bytes": "file_document",
        "yosoi::documents::FileDocument::byte_len": "file_document",
        "yosoi::documents::FileDocument::sha256": "file_document",
        "yosoi::documents::file_from_bytes": "file_document",
        "yosoi::documents::FileMetadata": "file_document",
        "yosoi::documents::FileMetadata::new": "file_document",
        "yosoi::documents::FileLimits": "file_document",
        "yosoi::documents::FileLimits::new": "file_limits",
        "yosoi::documents::FileLimits::max_bytes": "file_limits",
        "yosoi::documents::FileDocumentError": "file_too_large_error",
        "yosoi::documents::FileDocumentError::TooLarge": "file_too_large_error",
        "yosoi::documents::FileDocumentError::MetadataTooLong": "file_metadata_error",
    }
    for variant in ("Image", "Video", "Audio", "Binary"):
        operations[f"yosoi::documents::FileDocument::{variant}"] = "file_document"
    for method in (
        "with_filename",
        "with_declared_media_type",
        "with_source",
        "with_capture_id",
        "with_session_id",
        "with_tab_id",
        "with_download_id",
    ):
        operations[f"yosoi::documents::FileMetadata::{method}"] = "file_document"
    for document in (
        "ImageDocument",
        "VideoDocument",
        "AudioDocument",
        "BinaryDocument",
    ):
        operations[f"yosoi::documents::{document}"] = "typed_file_document"
        for method in (
            "from_bytes",
            "from_bytes_with_limits",
            "from_bytes_with_metadata",
        ):
            operations[f"yosoi::documents::{document}::{method}"] = (
                "typed_file_document"
            )
        for method in ("id", "metadata", "bytes", "byte_len", "sha256"):
            operations[f"yosoi::documents::{document}::{method}"] = (
                "typed_file_document"
            )
    cases = []
    workflow_by_kind = {
        kind: [
            item
            for item, given in zip(raw_comparisons, inputs, strict=True)
            if given["kind"] == kind
        ]
        for kind in (
            "query",
            "policy",
            "policy_error",
            "document",
            "contract",
            "contract_value_identity",
            "file_document",
            "file_limits",
            "file_too_large_error",
            "typed_file_document",
            "file_metadata_error",
        )
    }
    inputs_by_name = {item["name"]: item for item in inputs}
    default_workflows = {
        given["rust_type"]: item
        for item, given in zip(raw_comparisons, inputs, strict=True)
        if given["kind"] == "model_default"
    }
    clone_workflows = {
        given["rust_type"]: item
        for item, given in zip(raw_comparisons, inputs, strict=True)
        if given["kind"] == "model_clone"
    }
    rust_items = {item["symbolKey"]: item for item in rust["items"]}
    for entry in ledger["entries"]:
        kind = operations.get(entry["rustPath"])
        inventory_item = rust_items.get(entry.get("symbolKey")) or {}
        clone_type = (
            inventory_item.get("parentRustPath")
            if inventory_item.get("trait") == "Clone"
            else None
        )
        if clone_type in clone_workflows:
            kind = "model_clone"
        default_type = (
            entry["rustPath"]
            if entry["rustPath"] in default_workflows
            else inventory_item.get("parentRustPath")
            if inventory_item.get("kind") == "struct_field"
            or inventory_item.get("trait") == "Default"
            else None
        )
        if default_type in default_workflows:
            kind = "model_default"
        if kind is None or entry.get("decision") != "mapped":
            continue
        selected = (
            [clone_workflows[clone_type]]
            if kind == "model_clone"
            else [default_workflows[default_type]]
            if kind == "model_default"
            else workflow_by_kind[kind]
        )
        if kind == "query":
            method = entry["rustPath"].rsplit("::", 1)[-1]
            if method in {"new", "with_namespace", "with_default_namespace"}:
                selected = [
                    item
                    for item in selected
                    if inputs_by_name[item["name"]]["operation"] == method
                ]
            else:
                selected = [
                    item for item in selected if "error" not in item["rust"]["result"]
                ]
        if not selected:
            continue
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
