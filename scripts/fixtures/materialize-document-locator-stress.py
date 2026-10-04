#!/usr/bin/env python3

"""Materialize the pinned advanced locator corpus from its tracked archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from document_locator_oracles import (
    HTML_NAMESPACE,
    MATHML_NAMESPACE,
    SVG_NAMESPACE,
    adjusted_html_element_name,
    html_element_namespace,
)


ADVANCED_SCHEMA = "yosoi.document-locator-advanced-corpus.v1"
DOM_SCHEMA = "yosoi.rendered-dom.v1"
HTML_NAMESPACE_URI = "http://www.w3.org/1999/xhtml"
SVG_NAMESPACE_URI = "http://www.w3.org/2000/svg"
MATHML_NAMESPACE_URI = "http://www.w3.org/1998/Math/MathML"
XML_NAMESPACE_URI = "http://www.w3.org/XML/1998/namespace"
XMLNS_NAMESPACE_URI = "http://www.w3.org/2000/xmlns/"
XLINK_NAMESPACE_URI = "http://www.w3.org/1999/xlink"
DOM_NORMALIZER_ID = "yosoi-rendered-dom-cdp-snapshot"
DOM_NORMALIZER_VERSION = 2
DOM_ELEMENT_NAMESPACE_INFERENCE = "whatwg-html-foreign-content-with-svg-adjusted-names-v1"
DOM_ATTRIBUTE_NAMESPACE_INFERENCE = "foreign-elements-only-standard-xml-xmlns-xlink-prefixes-v2"
DOM_PSEUDO_ELEMENT_POLICY = "omit-pseudoType-index-and-double-colon-name-subtrees-v1"
DOM_EXCLUSIONS = [
    "shadow-dom",
    "iframe-subdocuments",
    "pseudo-elements",
    "flattened-composed-trees",
    "layout-visibility",
]
CHUNK_BYTES = 1024 * 1024


class MaterializationError(ValueError):
    """The retained source artifact cannot be materialized exactly as pinned."""


def ascii_lower(value: str) -> str:
    return "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character
        for character in value
    )


def _snapshot_string(strings: list[Any], index: Any, context: str) -> str:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(strings):
        raise MaterializationError(f"{context} has an invalid string-table index")
    value = strings[index]
    if not isinstance(value, str):
        raise MaterializationError(f"{context} does not resolve to a string")
    return value


def _attribute_namespace(name: str, element_namespace: str) -> tuple[str, str]:
    if element_namespace == HTML_NAMESPACE:
        return "", name
    if name == "xmlns":
        return XMLNS_NAMESPACE_URI, "xmlns"
    if name.startswith("xmlns:"):
        return XMLNS_NAMESPACE_URI, name.removeprefix("xmlns:")
    for prefix, namespace_uri in (
        ("xml", XML_NAMESPACE_URI),
        ("xlink", XLINK_NAMESPACE_URI),
    ):
        marker = f"{prefix}:"
        if name.startswith(marker):
            return namespace_uri, name.removeprefix(marker)
    if ":" in name:
        raise MaterializationError(
            f"foreign DOM attribute prefix has no canonical namespace mapping: {name!r}"
        )
    return "", name


def _canonical_attributes(
    strings: list[Any], values: Any, element_namespace: str, context: str
) -> list[dict[str, str]]:
    if not isinstance(values, list) or len(values) % 2 != 0:
        raise MaterializationError(f"{context} attribute data must be an even string-index list")
    attributes: list[dict[str, str]] = []
    for position in range(0, len(values), 2):
        raw_name = _snapshot_string(strings, values[position], f"{context} attribute name")
        value_index = values[position + 1]
        attribute_value = (
            ""
            if value_index == -1
            else _snapshot_string(strings, value_index, f"{context} attribute value")
        )
        namespace_uri, name = _attribute_namespace(raw_name, element_namespace)
        if not name or "\0" in name or "\0" in attribute_value:
            raise MaterializationError(f"{context} contains an invalid attribute string")
        attributes.append(
            {"namespace_uri": namespace_uri, "name": name, "value": attribute_value}
        )
    attributes.sort(key=lambda attribute: (attribute["namespace_uri"], attribute["name"]))
    for previous, current in zip(attributes, attributes[1:]):
        if (previous["namespace_uri"], previous["name"]) == (
            current["namespace_uri"],
            current["name"],
        ):
            raise MaterializationError(f"{context} contains a duplicate canonical attribute")
    return attributes


def normalize_rendered_dom_snapshot(raw_path: Path, entry: dict[str, Any]) -> bytes:
    provenance = entry.get("provenance")
    normalization = provenance.get("normalization") if isinstance(provenance, dict) else None
    if not isinstance(normalization, dict):
        raise MaterializationError("generated rendered-DOM entry has no normalizer authority")
    if (
        normalization.get("id") != DOM_NORMALIZER_ID
        or normalization.get("version") != DOM_NORMALIZER_VERSION
        or normalization.get("schema") != DOM_SCHEMA
        or normalization.get("element_namespace_inference")
        != DOM_ELEMENT_NAMESPACE_INFERENCE
        or normalization.get("attribute_namespace_inference")
        != DOM_ATTRIBUTE_NAMESPACE_INFERENCE
        or normalization.get("pseudo_element_policy") != DOM_PSEUDO_ELEMENT_POLICY
        or normalization.get("tree_model") != "document_light_dom"
        or normalization.get("exclusions") != DOM_EXCLUSIONS
    ):
        raise MaterializationError("generated rendered-DOM normalizer identity is unsupported")
    _, raw_digest = digest_file(raw_path)
    if raw_digest != normalization.get("source_sha256"):
        raise MaterializationError("raw DOMSnapshot digest differs from normalizer authority")

    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MaterializationError(f"cannot read raw DOMSnapshot {raw_path}: {error}") from error
    snapshot = raw.get("snapshot") if isinstance(raw, dict) else None
    documents = snapshot.get("documents") if isinstance(snapshot, dict) else None
    strings = snapshot.get("strings") if isinstance(snapshot, dict) else None
    if not isinstance(documents, list) or not documents or not isinstance(strings, list):
        raise MaterializationError("raw DOMSnapshot has no root document or string table")
    document = documents[0]
    nodes = document.get("nodes") if isinstance(document, dict) else None
    if not isinstance(nodes, dict):
        raise MaterializationError("raw DOMSnapshot root document has no node arrays")
    parent_indices = nodes.get("parentIndex")
    node_types = nodes.get("nodeType")
    node_names = nodes.get("nodeName")
    node_values = nodes.get("nodeValue")
    raw_attributes = nodes.get("attributes")
    if not all(
        isinstance(values, list)
        for values in (parent_indices, node_types, node_names, node_values, raw_attributes)
    ):
        raise MaterializationError("raw DOMSnapshot has missing node arrays")
    count = len(parent_indices)
    if count == 0 or any(
        len(values) != count
        for values in (node_types, node_names, node_values, raw_attributes)
    ):
        raise MaterializationError("raw DOMSnapshot node arrays have inconsistent lengths")

    root_indices: list[int] = []
    for index, (parent_index, node_type) in enumerate(zip(parent_indices, node_types)):
        if (
            not isinstance(parent_index, int)
            or isinstance(parent_index, bool)
            or not isinstance(node_type, int)
            or isinstance(node_type, bool)
        ):
            raise MaterializationError("raw DOMSnapshot has a non-integer node edge or type")
        if parent_index == -1:
            if node_type == 9:
                root_indices.append(index)
            elif index != 0:
                raise MaterializationError("raw DOMSnapshot has a second parentless node")
        elif not 0 <= parent_index < index:
            raise MaterializationError("raw DOMSnapshot parent indexes are not preorder edges")
    if len(root_indices) != 1 or root_indices[0] != 0:
        raise MaterializationError("raw DOMSnapshot must start with one document root")

    shadow_data = nodes.get("shadowRootType", {})
    shadow_indices = shadow_data.get("index", []) if isinstance(shadow_data, dict) else None
    if not isinstance(shadow_indices, list):
        raise MaterializationError("raw DOMSnapshot shadow-root metadata is malformed")
    shadow_roots: set[int] = set()
    for index in shadow_indices:
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < count:
            raise MaterializationError("raw DOMSnapshot has an invalid shadow-root index")
        shadow_roots.add(index)

    pseudo_data = nodes.get("pseudoType")
    if not isinstance(pseudo_data, dict) or set(pseudo_data) != {"index", "value"}:
        raise MaterializationError("raw DOMSnapshot pseudoType sparse data is malformed")
    pseudo_indices = pseudo_data.get("index")
    pseudo_value_indices = pseudo_data.get("value")
    if (
        not isinstance(pseudo_indices, list)
        or not isinstance(pseudo_value_indices, list)
        or len(pseudo_indices) != len(pseudo_value_indices)
    ):
        raise MaterializationError("raw DOMSnapshot pseudoType sparse arrays are inconsistent")

    pseudo_elements: set[int] = set()
    previous_pseudo_index = -1
    for index, type_value_index in zip(pseudo_indices, pseudo_value_indices):
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < count
            or index <= previous_pseudo_index
            or node_types[index] != 1
        ):
            raise MaterializationError("raw DOMSnapshot pseudoType has an invalid node index")
        pseudo_type = _snapshot_string(strings, type_value_index, "raw DOMSnapshot pseudo type")
        if not pseudo_type:
            raise MaterializationError("raw DOMSnapshot pseudoType value cannot be empty")
        pseudo_elements.add(index)
        previous_pseudo_index = index

    for index, node_type in enumerate(node_types):
        if node_type != 1:
            continue
        raw_name = _snapshot_string(strings, node_names[index], "raw DOMSnapshot element name")
        if raw_name.startswith("::"):
            pseudo_elements.add(index)

    suppressed = [False] * count
    for index, parent_index in enumerate(parent_indices):
        if index in shadow_roots or index in pseudo_elements or node_types[index] == 11:
            suppressed[index] = True
        elif parent_index >= 0 and suppressed[parent_index]:
            suppressed[index] = True

    epoch = normalization.get("document_epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or not 0 < epoch <= (1 << 64) - 1:
        raise MaterializationError("normalizer authority needs a non-zero u64 document epoch")

    namespace_uris = {
        HTML_NAMESPACE: HTML_NAMESPACE_URI,
        SVG_NAMESPACE: SVG_NAMESPACE_URI,
        MATHML_NAMESPACE: MATHML_NAMESPACE_URI,
    }
    output_nodes: list[dict[str, Any]] = []
    emitted: dict[int, dict[str, Any]] = {}
    for index in range(count):
        node_type = node_types[index]
        if suppressed[index] or node_type not in {1, 3, 9}:
            continue
        parent_index = parent_indices[index]
        while parent_index >= 0 and parent_index not in emitted:
            parent_index = parent_indices[parent_index]
        if index == root_indices[0]:
            record: dict[str, Any] = {
                "kind": "document",
                "id": index + 1,
                "parent": None,
                "children": [],
            }
        elif parent_index < 0:
            raise MaterializationError("raw DOMSnapshot node is outside its document tree")
        elif node_type == 3:
            value_index = node_values[index]
            if not isinstance(value_index, int) or isinstance(value_index, bool):
                raise MaterializationError("raw DOMSnapshot text node has an invalid value index")
            value = (
                ""
                if value_index == -1
                else _snapshot_string(strings, value_index, "raw DOMSnapshot text value")
            )
            record = {
                "kind": "text",
                "id": index + 1,
                "parent": parent_index + 1,
                "children": [],
                "value": value,
            }
        else:
            parent = emitted[parent_index]
            parent_namespace_uri = parent.get("namespace_uri")
            parent_namespace = next(
                (
                    namespace
                    for namespace, uri in namespace_uris.items()
                    if uri == parent_namespace_uri
                ),
                None,
            )
            parent_attributes = {
                attribute["name"]: attribute["value"]
                for attribute in parent.get("attributes", [])
                if attribute["namespace_uri"] == ""
            }
            raw_name = _snapshot_string(strings, node_names[index], "raw DOMSnapshot element name")
            token_name = ascii_lower(raw_name)
            namespace = html_element_namespace(
                parent_namespace,
                parent.get("tag_name"),
                parent_attributes,
                token_name,
            )
            namespace_uri = namespace_uris.get(namespace)
            if namespace_uri is None:
                raise MaterializationError("HTML namespace inference returned an unsupported URI")
            tag_name = adjusted_html_element_name(token_name, namespace)
            attributes = _canonical_attributes(
                strings,
                raw_attributes[index],
                namespace,
                f"raw DOMSnapshot element #{index}",
            )
            record = {
                "kind": "element",
                "id": index + 1,
                "parent": parent_index + 1,
                "children": [],
                "namespace_uri": namespace_uri,
                "tag_name": tag_name,
                "attributes": attributes,
            }
        emitted[index] = record
        output_nodes.append(record)
        if parent_index >= 0:
            emitted[parent_index]["children"].append(index + 1)

    if not output_nodes or output_nodes[0].get("kind") != "document":
        raise MaterializationError("normalization did not produce a document root")
    canonical = {
        "schema": DOM_SCHEMA,
        "document_epoch": epoch,
        "tree_model": "document_light_dom",
        "root": root_indices[0] + 1,
        "nodes": output_nodes,
    }
    return (json.dumps(canonical, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _synthetic_dom_snapshot(pseudo_indices: list[int], pseudo_values: list[int]) -> dict[str, Any]:
    return {
        "snapshot": {
            "strings": [
                "#document",
                "html",
                "span",
                "#text",
                "div",
                "must be omitted",
                "before",
            ],
            "documents": [
                {
                    "nodes": {
                        "parentIndex": [-1, 0, 1, 2, 1],
                        "nodeType": [9, 1, 1, 3, 1],
                        "nodeName": [0, 1, 2, 3, 4],
                        "nodeValue": [-1, -1, -1, 5, -1],
                        "attributes": [[], [], [], [], []],
                        "shadowRootType": {"index": [], "value": []},
                        "pseudoType": {"index": pseudo_indices, "value": pseudo_values},
                    }
                }
            ],
        }
    }


def _synthetic_namespace_dom_snapshot() -> dict[str, Any]:
    return {
        "snapshot": {
            "strings": [
                "#document",
                "html",
                "svg",
                "xml:lang",
                "en",
                "xmlns",
                HTML_NAMESPACE_URI,
                "xlink:href",
                "https://example.test/",
            ],
            "documents": [
                {
                    "nodes": {
                        "parentIndex": [-1, 0, 1],
                        "nodeType": [9, 1, 1],
                        "nodeName": [0, 1, 2],
                        "nodeValue": [-1, -1, -1],
                        "attributes": [[], [3, 4, 5, 6], [7, 8]],
                        "shadowRootType": {"index": [], "value": []},
                        "pseudoType": {"index": [], "value": []},
                    }
                }
            ],
        }
    }


def _synthetic_normalizer_entry(raw_bytes: bytes) -> dict[str, Any]:
    return {
        "document_kind": "dom",
        "schema_identity": DOM_SCHEMA,
        "provenance": {
            "kind": "normalized-derived",
            "normalization": {
                "id": DOM_NORMALIZER_ID,
                "version": DOM_NORMALIZER_VERSION,
                "schema": DOM_SCHEMA,
                "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "document_epoch": 9,
                "element_namespace_inference": DOM_ELEMENT_NAMESPACE_INFERENCE,
                "attribute_namespace_inference": DOM_ATTRIBUTE_NAMESPACE_INFERENCE,
                "pseudo_element_policy": DOM_PSEUDO_ELEMENT_POLICY,
                "tree_model": "document_light_dom",
                "exclusions": DOM_EXCLUSIONS,
            },
        },
    }


def run_normalizer_self_tests() -> None:
    with tempfile.TemporaryDirectory(prefix=".rendered-dom-normalizer-self-test-") as temporary:
        raw_path = Path(temporary) / "snapshot.json"
        valid_raw = _synthetic_dom_snapshot([2], [6])
        valid_bytes = json.dumps(valid_raw, separators=(",", ":")).encode("utf-8")
        raw_path.write_bytes(valid_bytes)
        canonical = json.loads(
            normalize_rendered_dom_snapshot(raw_path, _synthetic_normalizer_entry(valid_bytes))
        )
        nodes = canonical.get("nodes")
        if not isinstance(nodes, list) or [node.get("id") for node in nodes] != [1, 2, 5]:
            raise MaterializationError(
                "normalizer self-test failed to omit an ordinary-name pseudo node and its subtree"
            )
        if any(node.get("kind") == "text" or node.get("tag_name") == "span" for node in nodes):
            raise MaterializationError("normalizer self-test retained a pseudo-element descendant")

        malformed_raw = _synthetic_dom_snapshot([2], [])
        malformed_bytes = json.dumps(malformed_raw, separators=(",", ":")).encode("utf-8")
        raw_path.write_bytes(malformed_bytes)
        try:
            normalize_rendered_dom_snapshot(
                raw_path,
                _synthetic_normalizer_entry(malformed_bytes),
            )
        except MaterializationError:
            pass
        else:
            raise MaterializationError("normalizer self-test accepted malformed pseudoType arrays")

        namespace_raw = _synthetic_namespace_dom_snapshot()
        namespace_bytes = json.dumps(namespace_raw, separators=(",", ":")).encode("utf-8")
        raw_path.write_bytes(namespace_bytes)
        namespace_document = json.loads(
            normalize_rendered_dom_snapshot(
                raw_path,
                _synthetic_normalizer_entry(namespace_bytes),
            )
        )
        namespace_nodes = namespace_document.get("nodes")
        if not isinstance(namespace_nodes, list) or len(namespace_nodes) != 3:
            raise MaterializationError("normalizer self-test produced an invalid namespace fixture")
        html_attributes = namespace_nodes[1].get("attributes")
        svg_attributes = namespace_nodes[2].get("attributes")
        if html_attributes != [
            {"namespace_uri": "", "name": "xml:lang", "value": "en"},
            {"namespace_uri": "", "name": "xmlns", "value": HTML_NAMESPACE_URI},
        ]:
            raise MaterializationError("normalizer self-test namespace-adjusted HTML attributes")
        if svg_attributes != [
            {"namespace_uri": XLINK_NAMESPACE_URI, "name": "href", "value": "https://example.test/"}
        ]:
            raise MaterializationError("normalizer self-test did not map a foreign xlink attribute")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MaterializationError(f"cannot read manifest {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != ADVANCED_SCHEMA:
        raise MaterializationError(f"unsupported advanced manifest schema in {path}")
    if not isinstance(value.get("files"), list):
        raise MaterializationError("advanced manifest files must be a list")
    return value


def relative_path(value: Any, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise MaterializationError(f"{context} has an invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise MaterializationError(f"{context} path must stay inside the corpus: {value!r}")
    return Path(*path.parts)


def digest_file(path: Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(CHUNK_BYTES):
                size += len(chunk)
                digest.update(chunk)
    except OSError as error:
        raise MaterializationError(f"cannot read {path}: {error}") from error
    return size, digest.hexdigest()


def verify_file(path: Path, entry: dict[str, Any], context: str) -> None:
    size, sha256 = digest_file(path)
    if size != entry.get("bytes") or sha256 != entry.get("sha256"):
        raise MaterializationError(f"{context} does not match pinned bytes and SHA-256")


def copy_member(source: BinaryIO, target: Path, entry: dict[str, Any]) -> None:
    size = 0
    digest = hashlib.sha256()
    try:
        with target.open("wb") as output:
            while chunk := source.read(CHUNK_BYTES):
                size += len(chunk)
                digest.update(chunk)
                output.write(chunk)
    except OSError as error:
        raise MaterializationError(f"cannot write staged fixture {target}: {error}") from error
    if size != entry.get("bytes") or digest.hexdigest() != entry.get("sha256"):
        raise MaterializationError(
            f"archive member {entry.get('path')} does not match pinned bytes and SHA-256"
        )


def artifact_entry(manifest: dict[str, Any]) -> dict[str, Any]:
    storage = manifest.get("storage")
    artifact = storage.get("source_artifact") if isinstance(storage, dict) else None
    if not isinstance(artifact, dict):
        raise MaterializationError("advanced manifest does not name a source artifact")
    if artifact.get("format") != "tar+gzip":
        raise MaterializationError("advanced source artifact must use tar+gzip")
    relative_path(artifact.get("path"), "advanced source artifact")
    return artifact


def default_manifest() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "benchmarks/fixtures/document-locators/v1/advanced/manifest.json"
    )


def default_archive(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    artifact = artifact_entry(manifest)
    return manifest_path.parent / relative_path(artifact["path"], "advanced source artifact")


def default_destination(manifest_path: Path) -> Path:
    return manifest_path.parent / "materialized"


def verify_existing(destination: Path, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        relative = relative_path(entry.get("path"), f"advanced fixture {entry.get('id')}")
        verify_file(destination / relative, entry, f"advanced fixture {entry.get('id')}")


def write_generated_dom(
    staging: Path,
    entry: dict[str, Any],
    entries_by_id: dict[str, dict[str, Any]],
) -> None:
    provenance = entry.get("provenance")
    normalization = provenance.get("normalization") if isinstance(provenance, dict) else None
    if (
        entry.get("document_kind") != "dom"
        or entry.get("schema_identity") != DOM_SCHEMA
        or not isinstance(normalization, dict)
    ):
        raise MaterializationError("generated fixture is not a canonical rendered-DOM output")
    source_id = normalization.get("source_fixture_id") if isinstance(normalization, dict) else None
    source_entry = entries_by_id.get(source_id) if isinstance(source_id, str) else None
    if source_entry is None or source_entry.get("document_kind") != "dom":
        raise MaterializationError("generated rendered-DOM entry names no raw DOMSnapshot source")
    source = staging / relative_path(source_entry["path"], "raw DOMSnapshot source")
    data = normalize_rendered_dom_snapshot(source, entry)
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != entry.get("bytes") or digest != entry.get("sha256"):
        raise MaterializationError(
            "normalized rendered-DOM output differs from its pinned byte count or SHA-256"
        )
    target = staging / relative_path(entry.get("path"), "generated rendered-DOM output")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as output:
            output.write(data)
    except OSError as error:
        raise MaterializationError(f"cannot write generated fixture {target}: {error}") from error


def derive_rendered_dom_pins(archive: Path, manifest: dict[str, Any]) -> None:
    run_normalizer_self_tests()
    entries = manifest.get("files")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise MaterializationError("advanced manifest file entries must be objects")
    entries_by_id = {entry.get("id"): entry for entry in entries}
    generated = [
        entry
        for entry in entries
        if isinstance(entry.get("provenance"), dict)
        and entry["provenance"].get("kind") == "normalized-derived"
    ]
    if not generated:
        raise MaterializationError("advanced manifest has no generated rendered-DOM entry")
    verify_file(archive, artifact_entry(manifest), "advanced source artifact")
    reports: list[dict[str, Any]] = []
    try:
        opened = tarfile.open(archive, mode="r:gz")
    except (OSError, tarfile.TarError) as error:
        raise MaterializationError(f"cannot open advanced source artifact {archive}: {error}") from error
    with opened, tempfile.TemporaryDirectory(prefix=".document-locator-dom-pins-") as temporary:
        temporary_root = Path(temporary)
        for entry in generated:
            normalization = entry.get("provenance", {}).get("normalization", {})
            source_entry = entries_by_id.get(normalization.get("source_fixture_id"))
            if not isinstance(source_entry, dict):
                raise MaterializationError("generated DOM entry names no raw DOMSnapshot source")
            source_name = relative_path(source_entry.get("path"), "raw DOMSnapshot source").as_posix()
            try:
                member = opened.getmember(source_name)
            except KeyError as error:
                raise MaterializationError(f"raw DOMSnapshot source is absent: {source_name}") from error
            source_stream = opened.extractfile(member)
            if source_stream is None:
                raise MaterializationError(f"cannot read raw DOMSnapshot source {source_name}")
            source_path = temporary_root / "raw-dom-snapshot.json"
            with source_stream:
                copy_member(source_stream, source_path, source_entry)
            normalized = normalize_rendered_dom_snapshot(source_path, entry)
            reports.append(
                {
                    "id": entry.get("id"),
                    "path": entry.get("path"),
                    "bytes": len(normalized),
                    "sha256": hashlib.sha256(normalized).hexdigest(),
                }
            )
    print(json.dumps(reports, ensure_ascii=False, separators=(",", ":")))


def materialize(archive: Path, destination: Path, manifest: dict[str, Any]) -> None:
    run_normalizer_self_tests()
    entries = manifest["files"]
    if not all(isinstance(entry, dict) for entry in entries):
        raise MaterializationError("advanced manifest file entries must be objects")
    verify_file(archive, artifact_entry(manifest), "advanced source artifact")

    if destination.exists():
        verify_existing(destination, entries)
        print(f"advanced corpus already materialized and verified at {destination}")
        return

    entries_by_id = {entry["id"]: entry for entry in entries}
    generated = [
        entry
        for entry in entries
        if isinstance(entry.get("provenance"), dict)
        and entry["provenance"].get("kind") == "normalized-derived"
    ]
    expected = {
        relative_path(entry.get("path"), f"advanced fixture {entry.get('id')}").as_posix(): entry
        for entry in entries
        if entry not in generated
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        opened = tarfile.open(archive, mode="r:gz")
    except (OSError, tarfile.TarError) as error:
        raise MaterializationError(f"cannot open advanced source artifact {archive}: {error}") from error

    with opened, tempfile.TemporaryDirectory(
        prefix=".document-locator-materialize-", dir=destination.parent
    ) as temporary:
        members = opened.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise MaterializationError("advanced source artifact members do not match the manifest")
        if not all(member.isfile() for member in members):
            raise MaterializationError("advanced source artifact may contain only regular files")

        staging = Path(temporary) / "materialized"
        for member in members:
            entry = expected[member.name]
            source = opened.extractfile(member)
            if source is None:
                raise MaterializationError(f"cannot read archive member {member.name}")
            target = staging / relative_path(member.name, "advanced archive member")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source:
                copy_member(source, target, entry)
        for entry in generated:
            write_generated_dom(staging, entry, entries_by_id)
        staging.rename(destination)
    print(f"materialized and verified {len(entries)} files at {destination}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_manifest())
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument(
        "--derive-rendered-dom-pins",
        action="store_true",
        help="print canonical rendered-DOM byte and SHA-256 pins without publishing the corpus",
    )
    arguments = parser.parse_args()
    try:
        manifest_path = arguments.manifest.resolve()
        manifest = load_manifest(manifest_path)
        archive = arguments.archive or default_archive(manifest_path, manifest)
        destination = arguments.destination or default_destination(manifest_path)
        if arguments.derive_rendered_dom_pins:
            if arguments.destination is not None:
                raise MaterializationError("--destination cannot be used with --derive-rendered-dom-pins")
            derive_rendered_dom_pins(archive.resolve(), manifest)
        else:
            materialize(archive.resolve(), destination.resolve(), manifest)
    except MaterializationError as error:
        print(f"advanced corpus not materialized: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
