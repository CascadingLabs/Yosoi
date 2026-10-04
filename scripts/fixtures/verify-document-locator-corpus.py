#!/usr/bin/env python3

"""Verify the offline ys.Documents/ys.Locators conformance corpus."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from document_locator_oracles import (
    OracleError,
    canonical_records_sha256,
    dom_attribute_value,
    document_node_records,
    json_document,
    json_path_results,
    json_pointer_result,
    locate_dom,
    node_order,
    validate_advanced_dom_case,
    validate_advanced_html_case,
    validate_case,
    validate_html_region_case,
    validate_svg_tag_name_adjustments,
)


CORPUS_SCHEMA = "yosoi.document-locator-corpus.v1"
MATRIX_SCHEMA = "yosoi.document-locator-matrix.v1"
ADVANCED_SCHEMA = "yosoi.document-locator-advanced-corpus.v1"
DOM_SCHEMA = "yosoi.rendered-dom.v1"
DOM_NORMALIZER_ID = "yosoi-rendered-dom-cdp-snapshot"
DOM_NORMALIZER_VERSION = 2
AX_SCHEMA = "yosoi.accessibility-tree.v1"
MAX_AX_NODES = 100_000
MAX_AX_DEPTH = 1_024
HTML_PROFILE = "html5-static-utf8-v1"
SUPPORTED_PAIRS = {
    ("html", "css"),
    ("html", "xpath"),
    ("html", "text"),
    ("xml", "css"),
    ("xml", "xpath"),
    ("xml", "text"),
    ("json", "json_pointer"),
    ("json", "json_path"),
    ("dom", "css"),
    ("dom", "xpath"),
    ("dom", "text"),
    ("ax", "role"),
    ("ax", "text"),
    ("text", "text"),
    ("text", "regex"),
}
SUPPORTED_CASES = {
    "html_css": ("html", "css", "text"),
    "html_xpath": ("html", "xpath", "attribute"),
    "html_text": ("html", "text", "node_reference"),
    "xml_css": ("xml", "css", "text"),
    "xml_xpath": ("xml", "xpath", "attribute"),
    "xml_text": ("xml", "text", "node_reference"),
    "json_pointer": ("json", "json_pointer", "json_value"),
    "json_path": ("json", "json_path", "json_value"),
    "dom_css": ("dom", "css", "text"),
    "dom_xpath": ("dom", "xpath", "attribute"),
    "dom_text": ("dom", "text", "node_reference"),
    "ax_role": ("ax", "role", "node_reference"),
    "ax_text": ("ax", "text", "text"),
    "text_text": ("text", "text", "text"),
    "text_regex": ("text", "regex", "matched_text_with_captures"),
}
FIXTURE_KINDS = {"html", "xml", "json", "dom", "ax", "text"}

BENCHMARK_REGISTRY = (
    ("html", "golden-html-products", "parse", "document_locator_html/parse/golden_products"),
    ("html", "golden-html-products", "locate", "document_locator_html/locate/golden_products"),
    (
        "html",
        "golden-html-products",
        "end_to_end",
        "document_locator_html/end_to_end/golden_products",
    ),
    ("dom", "golden-dom-products", "parse", "document_locator_rendered_dom/parse/golden_products"),
    ("dom", "golden-dom-products", "locate", "document_locator_rendered_dom/locate/golden_products"),
    (
        "dom",
        "golden-dom-products",
        "end_to_end",
        "document_locator_rendered_dom/end_to_end/golden_products",
    ),
    (
        "dom",
        "advanced-wcag-rendered-dom-v1",
        "parse",
        "document_locator_rendered_dom/parse/advanced_wcag",
    ),
    (
        "text",
        "golden-text-orders",
        "plan_compile",
        "document_locator/plan_compile/golden_orders",
    ),
    ("text", "golden-text-orders", "parse", "document_locator/parse/golden_orders"),
    ("text", "golden-text-orders", "locate", "document_locator/locate/golden_orders"),
    (
        "text",
        "golden-text-orders",
        "materialize",
        "document_locator/materialize/golden_orders",
    ),
    (
        "text",
        "golden-text-orders",
        "end_to_end",
        "document_locator/end_to_end/golden_orders",
    ),
    ("text", "advanced-whatwg-text", "plan_compile", "document_locator/plan_compile/advanced_whatwg"),
    ("text", "advanced-whatwg-text", "parse", "document_locator/parse/advanced_whatwg"),
    ("text", "advanced-whatwg-text", "locate", "document_locator/locate/advanced_whatwg"),
    ("text", "advanced-whatwg-text", "materialize", "document_locator/materialize/advanced_whatwg"),
    ("text", "advanced-whatwg-text", "end_to_end", "document_locator/end_to_end/advanced_whatwg"),
    ("json", "golden-json-products", "parse", "document_locator_json_parse/golden_product_json"),
    (
        "json",
        "golden-json-products",
        "locate",
        "document_locator_json_locate/golden_pointer_and_jsonpath",
    ),
    (
        "json",
        "golden-json-products",
        "end_to_end",
        "document_locator_json_end_to_end/golden_pointer_and_jsonpath",
    ),
    ("xml", "golden-xml-catalog", "parse", "document_locator/xml/parse"),
    ("xml", "golden-xml-catalog", "locate", "document_locator/xml/locate"),
    ("xml", "golden-xml-catalog", "end_to_end", "document_locator/xml/end_to_end"),
    (
        "ax",
        "golden-ax-products",
        "parse",
        "document_locator/ax/parse/golden_accessibility_tree",
    ),
    ("ax", "golden-ax-products", "locate", "document_locator/ax/locate/ax_role"),
    ("ax", "golden-ax-products", "end_to_end", "document_locator/ax/end_to_end/ax_role"),
    ("ax", "golden-ax-products", "locate", "document_locator/ax/locate/ax_name"),
    ("ax", "golden-ax-products", "end_to_end", "document_locator/ax/end_to_end/ax_name"),
    ("ax", "golden-ax-products", "locate", "document_locator/ax/locate/ax_text"),
    ("ax", "golden-ax-products", "end_to_end", "document_locator/ax/end_to_end/ax_text"),
    ("ax", "golden-ax-products", "locate", "document_locator/ax/locate/ax_state"),
    ("ax", "golden-ax-products", "end_to_end", "document_locator/ax/end_to_end/ax_state"),
)


class CorpusError(ValueError):
    """The committed corpus or a materialized stress file is invalid."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CorpusError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise CorpusError(f"{path} must contain a JSON object")
    return value


def require_keys(value: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys.difference(value))
    if missing:
        raise CorpusError(f"{context} is missing keys: {', '.join(missing)}")


def safe_relative_path(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise CorpusError(f"{context} has an invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise CorpusError(f"{context} path must stay inside the corpus: {value!r}")
    return value


def read_fixture(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise CorpusError(f"cannot read fixture {path}: {error}") from error


def validate_file(path: Path, entry: dict[str, Any], context: str) -> bytes:
    data = read_fixture(path)
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if len(data) != entry.get("bytes"):
        raise CorpusError(
            f"{context} byte mismatch: expected {entry.get('bytes')}, got {len(data)}"
        )
    if actual_sha256 != entry.get("sha256"):
        raise CorpusError(
            f"{context} digest mismatch: expected {entry.get('sha256')}, got {actual_sha256}"
        )
    return data


def validate_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") != CORPUS_SCHEMA:
        raise CorpusError(f"unsupported corpus schema: {manifest.get('schema')!r}")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise CorpusError("corpus manifest files must be a list")

    by_id: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for index, entry in enumerate(files):
        context = f"corpus file #{index}"
        if not isinstance(entry, dict):
            raise CorpusError(f"{context} must be an object")
        require_keys(
            entry,
            {
                "id",
                "path",
                "document_kind",
                "schema_identity",
                "media_type",
                "encoding",
                "bytes",
                "sha256",
                "source_url",
                "captured_at",
                "provenance",
            },
            context,
        )
        fixture_id = entry["id"]
        relative_path = safe_relative_path(entry["path"], context)
        if not isinstance(fixture_id, str) or not fixture_id:
            raise CorpusError(f"{context} has an invalid id")
        if fixture_id in by_id:
            raise CorpusError(f"duplicate fixture id: {fixture_id}")
        if relative_path in paths:
            raise CorpusError(f"duplicate fixture path: {relative_path}")
        if entry["document_kind"] not in FIXTURE_KINDS:
            raise CorpusError(f"{context} has unknown document kind")
        if fixture_id == "golden-html-products" and entry["schema_identity"] != HTML_PROFILE:
            raise CorpusError(f"{context} must pin the static UTF-8 HTML parser profile")
        if fixture_id == "golden-dom-products" and (
            entry["document_kind"] != "dom" or entry["schema_identity"] != DOM_SCHEMA
        ):
            raise CorpusError(f"{context} must pin the canonical rendered-DOM schema")
        if entry["encoding"] != "utf-8":
            raise CorpusError(f"{context} must be canonical UTF-8")
        if not isinstance(entry["provenance"], dict):
            raise CorpusError(f"{context} provenance must be an object")
        validate_file(root / relative_path, entry, context)
        if entry["document_kind"] == "dom":
            load_node_fixture(root / relative_path, "dom")
        by_id[fixture_id] = entry
        paths.add(relative_path)

    if {entry["document_kind"] for entry in files} != FIXTURE_KINDS:
        raise CorpusError("golden corpus must contain exactly all six document kinds")
    return by_id


def resolve_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise CorpusError(f"invalid JSON Pointer: {pointer!r}")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise CorpusError(f"JSON Pointer traverses a scalar: {pointer!r}")
        except (KeyError, IndexError, ValueError) as error:
            raise CorpusError(f"JSON Pointer does not resolve: {pointer!r}") from error
    return current


def ascii_lower(value: str) -> str:
    return "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character
        for character in value
    )


def _positive_u64(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 < value <= (1 << 64) - 1
    )


def _is_control(character: str) -> bool:
    codepoint = ord(character)
    return codepoint < 0x20 or 0x7F <= codepoint <= 0x9F


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and all(
        character != "\0"
        and (not _is_control(character) or character in "\t\n\r\f\v")
        for character in value
    )


def _valid_name(value: Any, *, allow_colon: bool = False) -> bool:
    return isinstance(value, str) and bool(value) and all(
        not character.isspace()
        and not _is_control(character)
        and character not in '<>="\'`/ '
        and (allow_colon or character != ":")
        for character in value
    )


def validate_rendered_dom_fixture(value: dict[str, Any], context: str) -> tuple[int, set[int]]:
    keys = {"schema", "document_epoch", "tree_model", "root", "nodes"}
    require_keys(value, keys, context)
    if set(value) != keys:
        raise CorpusError(f"{context} has unknown fields")
    if value.get("schema") != DOM_SCHEMA:
        raise CorpusError(f"{context} must use {DOM_SCHEMA}")
    if value.get("tree_model") != "document_light_dom":
        raise CorpusError(f"{context} has an unsupported tree model")
    epoch = value.get("document_epoch")
    root_id = value.get("root")
    nodes = value.get("nodes")
    if not _positive_u64(epoch) or not _positive_u64(root_id):
        raise CorpusError(f"{context} epoch and root must be non-zero u64 values")
    if not isinstance(nodes, list) or not nodes or not all(
        isinstance(node, dict) for node in nodes
    ):
        raise CorpusError(f"{context} nodes must be a non-empty list of objects")

    by_id: dict[int, dict[str, Any]] = {}
    ordered_ids: list[int] = []
    document_ids: list[int] = []
    for index, node in enumerate(nodes):
        node_context = f"{context} node #{index}"
        node_id = node.get("id")
        if not _positive_u64(node_id) or node_id in by_id:
            raise CorpusError(f"{node_context} needs a unique non-zero u64 id")
        kind = node.get("kind")
        if kind == "document":
            expected_keys = {"kind", "id", "parent", "children"}
            document_ids.append(node_id)
        elif kind == "element":
            expected_keys = {
                "kind",
                "id",
                "parent",
                "children",
                "namespace_uri",
                "tag_name",
                "attributes",
            }
            namespace_uri = node.get("namespace_uri")
            tag_name = node.get("tag_name")
            attributes = node.get("attributes")
            if (
                not isinstance(namespace_uri, str)
                or any(_is_control(character) or character.isspace() for character in namespace_uri)
                or not _valid_name(tag_name)
                or not isinstance(attributes, list)
            ):
                raise CorpusError(f"{node_context} has invalid element namespace, tag, or attributes")
            attribute_keys: list[tuple[str, str]] = []
            seen_attributes: set[tuple[str, str]] = set()
            for attribute_index, attribute in enumerate(attributes):
                attribute_context = f"{node_context} attribute #{attribute_index}"
                if not isinstance(attribute, dict) or set(attribute) != {
                    "namespace_uri",
                    "name",
                    "value",
                }:
                    raise CorpusError(f"{attribute_context} has an unsupported shape")
                attribute_namespace = attribute.get("namespace_uri")
                attribute_name = attribute.get("name")
                attribute_value = attribute.get("value")
                if (
                    not isinstance(attribute_namespace, str)
                    or (
                        attribute_namespace != ""
                        and any(
                            _is_control(character) or character.isspace()
                            for character in attribute_namespace
                        )
                    )
                    or not _valid_name(attribute_name, allow_colon=attribute_namespace == "")
                    or not _valid_text(attribute_value)
                ):
                    raise CorpusError(f"{attribute_context} has invalid strings")
                sort_key = (attribute_namespace, attribute_name)
                if attribute_keys and attribute_keys[-1] >= sort_key:
                    raise CorpusError(f"{node_context} attributes are not in canonical order")
                attribute_keys.append(sort_key)
                unique_name = (
                    ascii_lower(attribute_name)
                    if namespace_uri == "http://www.w3.org/1999/xhtml"
                    and attribute_namespace == ""
                    else attribute_name
                )
                unique_key = (attribute_namespace, unique_name)
                if unique_key in seen_attributes:
                    raise CorpusError(f"{node_context} has a duplicate attribute")
                seen_attributes.add(unique_key)
        elif kind == "text":
            expected_keys = {"kind", "id", "parent", "children", "value"}
            text_value = node.get("value")
            if not _valid_text(text_value):
                raise CorpusError(f"{node_context} has invalid text")
        else:
            raise CorpusError(f"{node_context} has an unsupported kind")
        if set(node) != expected_keys:
            raise CorpusError(f"{node_context} has unknown or missing fields")
        parent = node.get("parent")
        children = node.get("children")
        if parent is not None and not _positive_u64(parent):
            raise CorpusError(f"{node_context} parent must be null or a non-zero u64 id")
        if not isinstance(children, list) or any(
            not _positive_u64(child_id) for child_id in children
        ) or len(set(children)) != len(children):
            raise CorpusError(f"{node_context} children must be unique non-zero u64 ids")
        if kind == "document" and parent is not None:
            raise CorpusError(f"{node_context} document parent must be null")
        if kind != "document" and parent is None:
            raise CorpusError(f"{node_context} non-root parent must name an id")
        if kind == "text" and children:
            raise CorpusError(f"{node_context} text children must be empty")
        by_id[node_id] = node
        ordered_ids.append(node_id)

    if len(document_ids) != 1 or document_ids[0] != root_id:
        raise CorpusError(f"{context} must have one document node named by root")
    if by_id[root_id].get("parent") is not None:
        raise CorpusError(f"{context} document root cannot have a parent")
    document_children = by_id[root_id].get("children")
    if (
        not isinstance(document_children, list)
        or len(document_children) != 1
        or by_id.get(document_children[0], {}).get("kind") != "element"
    ):
        raise CorpusError(f"{context} document root must have exactly one element child")

    for node in nodes:
        parent = node["parent"]
        kind = node["kind"]
        if parent is not None:
            parent_node = by_id.get(parent)
            if parent_node is None or parent_node["kind"] not in {"document", "element"}:
                raise CorpusError(f"{context} node parent must be a document or element")
            if node["id"] not in parent_node["children"]:
                raise CorpusError(f"{context} parent/child edges disagree")
            if kind == "document":
                raise CorpusError(f"{context} contains a non-root document node")
        for child_id in node["children"]:
            child = by_id.get(child_id)
            if child is None or child.get("parent") != node["id"]:
                raise CorpusError(f"{context} parent/child edges disagree")

    preorder: list[int] = []
    pending = [root_id]
    seen_ids: set[int] = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen_ids:
            raise CorpusError(f"{context} contains a cycle or repeated child")
        node = by_id.get(node_id)
        if node is None:
            raise CorpusError(f"{context} references an unknown node")
        seen_ids.add(node_id)
        preorder.append(node_id)
        pending.extend(reversed(node["children"]))
    if len(preorder) != len(nodes) or preorder != ordered_ids:
        raise CorpusError(f"{context} nodes must be reachable in child-order preorder")
    return epoch, set(ordered_ids)


def load_node_fixture(path: Path, document_kind: str) -> tuple[Any, set[Any]]:
    value = load_json(path)
    expected_schema = DOM_SCHEMA if document_kind == "dom" else AX_SCHEMA
    if value.get("schema") != expected_schema:
        raise CorpusError(
            f"{document_kind} fixture must use {expected_schema}, got {value.get('schema')!r}"
        )
    if document_kind == "dom":
        return validate_rendered_dom_fixture(value, str(path))
    if set(value) != {"schema", "document_epoch", "root", "completeness", "nodes"}:
        raise CorpusError("AX fixture top-level fields must match the v1 schema")
    epoch = value.get("document_epoch")
    nodes = value.get("nodes")
    epoch_valid = (
        isinstance(epoch, str) and bool(epoch)
        if document_kind == "dom"
        else type(epoch) is int and epoch > 0
    )
    if not epoch_valid or not isinstance(nodes, list) or not nodes:
        raise CorpusError(f"{document_kind} fixture has invalid epoch or nodes")
    if document_kind == "ax" and len(nodes) > MAX_AX_NODES:
        raise CorpusError("AX fixture exceeds the v1 node-count limit")
    if not all(isinstance(node, dict) for node in nodes):
        raise CorpusError(f"{document_kind} fixture nodes must be objects")
    node_values = [node.get("id") for node in nodes]
    if not all(isinstance(node_id, str) and node_id.strip() for node_id in node_values):
        raise CorpusError(f"{document_kind} fixture node ids must be non-empty strings")
    node_ids = set(node_values)
    if len(node_ids) != len(nodes):
        raise CorpusError(f"{document_kind} fixture node ids must be unique strings")
    root_id = value.get("root")
    if not isinstance(root_id, str) or root_id not in node_ids:
        raise CorpusError(f"{document_kind} fixture root does not name a node")
    by_id = {node["id"]: node for node in nodes}
    if by_id[root_id].get("parent") is not None:
        raise CorpusError(f"{document_kind} fixture root cannot have a parent")
    if document_kind == "ax":
        completeness = value.get("completeness")
        if not isinstance(completeness, dict) or completeness.get("status") not in {
            "complete",
            "partial",
            "unknown",
        }:
            raise CorpusError("AX fixture completeness must be complete, partial, or unknown")
        if completeness["status"] == "complete":
            if set(completeness) != {"status"}:
                raise CorpusError("complete AX fixture completeness has unexpected fields")
        else:
            if not isinstance(completeness.get("reason_code"), str) or not completeness[
                "reason_code"
            ].strip():
                raise CorpusError("incomplete AX fixtures need a reason code")
            if completeness["status"] == "partial":
                lost_items = completeness.get("lost_items")
                if lost_items is not None and (type(lost_items) is not int or lost_items <= 0):
                    raise CorpusError("partial AX lost_items must be a positive integer")
                if set(completeness).difference({"status", "reason_code", "lost_items"}):
                    raise CorpusError("partial AX completeness has unexpected fields")
            elif set(completeness) != {"status", "reason_code"}:
                raise CorpusError("unknown AX completeness has unexpected fields")

    incoming_edges = dict.fromkeys(node_ids, 0)
    for node in nodes:
        parent = node.get("parent")
        children = node.get("children")
        if parent is not None and (not isinstance(parent, str) or parent not in node_ids):
            raise CorpusError(f"{document_kind} fixture node has an unknown parent")
        if not isinstance(children, list) or not all(isinstance(child, str) for child in children):
            raise CorpusError(f"{document_kind} fixture children must be a list of ids")
        if len(set(children)) != len(children):
            raise CorpusError(f"{document_kind} fixture children must be a unique list")
        for child_id in children:
            if child_id not in by_id or by_id[child_id].get("parent") != node["id"]:
                raise CorpusError(f"{document_kind} fixture parent/child edges disagree")
            incoming_edges[child_id] += 1
        if set(node) != {
            "id",
            "parent",
            "children",
            "ignored",
            "role",
            "accessible_name",
            "text",
            "states",
        }:
            raise CorpusError("AX fixture node fields must match the v1 schema")
        if not isinstance(node.get("role"), str) or not node["role"].strip():
            raise CorpusError("AX fixture nodes need an exact non-empty role")
        if type(node.get("ignored")) is not bool:
            raise CorpusError("AX fixture ignored must be boolean")
        for field_name in ["accessible_name", "text"]:
            field_value = node.get(field_name)
            if field_value is not None and not isinstance(field_value, str):
                raise CorpusError(f"AX fixture {field_name} must be text or null")
        states = node.get("states")
        if not isinstance(states, dict) or set(states).difference({"expanded", "focused"}):
            raise CorpusError("AX fixture states must use the supported v1 names")
        if not all(type(state_value) is bool for state_value in states.values()):
            raise CorpusError("AX fixture state values must be boolean scalars")
    for node_id, node in by_id.items():
        if node_id == root_id:
            if incoming_edges[node_id] != 0:
                raise CorpusError("AX/DOM root cannot be referenced as a child")
        elif node.get("parent") is None or incoming_edges[node_id] != 1:
            raise CorpusError("AX/DOM non-root nodes need one parent edge")

    visit_state: dict[str, int] = {}
    for start_id in node_ids:
        trail: list[str] = []
        current_id: str | None = start_id
        while current_id is not None:
            state = visit_state.get(current_id, 0)
            if state == 1:
                raise CorpusError(f"{document_kind} fixture contains a parent cycle")
            if state == 2:
                break
            visit_state[current_id] = 1
            trail.append(current_id)
            current_id = by_id[current_id].get("parent")
        for node_id in trail:
            visit_state[node_id] = 2

    reachable: set[str] = set()
    pending = [(root_id, 1)]
    while pending:
        current_id, depth = pending.pop()
        if document_kind == "ax" and depth > MAX_AX_DEPTH:
            raise CorpusError("AX fixture exceeds the v1 tree-depth limit")
        if current_id in reachable:
            raise CorpusError(f"{document_kind} fixture contains a duplicate tree edge")
        reachable.add(current_id)
        pending.extend((child_id, depth + 1) for child_id in by_id[current_id]["children"])
    if reachable != node_ids:
        raise CorpusError(f"{document_kind} fixture contains nodes outside the root tree")
    return epoch, node_ids


def validate_expected_match(
    root: Path,
    fixture: dict[str, Any],
    match: dict[str, Any],
    context: str,
    fixture_root: Path | None = None,
    fixture_bytes: bytes | None = None,
) -> None:
    require_keys(match, {"value", "coordinate"}, context)
    coordinate = match["coordinate"]
    if not isinstance(coordinate, dict):
        raise CorpusError(f"{context} coordinate must be an object")
    kind = coordinate.get("kind")
    fixture_path = (fixture_root or root) / fixture["path"]
    document_kind = fixture["document_kind"]
    if kind == "source_tree_path":
        if document_kind != "html":
            raise CorpusError(f"{context} parser tree path is invalid for {document_kind}")
        require_keys(coordinate, {"child_path", "path"}, f"{context} coordinate")
        child_path = coordinate["child_path"]
        if (
            not isinstance(child_path, list)
            or not child_path
            or any(not isinstance(part, int) or isinstance(part, bool) or part < 1 for part in child_path)
            or not isinstance(coordinate["path"], str)
            or not coordinate["path"].startswith("/")
        ):
            raise CorpusError(f"{context} has an invalid HTML parser tree path")
    elif kind == "source_byte_range":
        if document_kind != "xml":
            raise CorpusError(f"{context} source byte range is only supported for XML")
        require_keys(coordinate, {"start", "end", "path"}, f"{context} coordinate")
        start, end = coordinate["start"], coordinate["end"]
        size = fixture["bytes"]
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= size:
            raise CorpusError(f"{context} has an invalid source byte range")
    elif kind == "decoded_text_byte_range":
        if document_kind != "text":
            raise CorpusError(f"{context} decoded-text range is invalid for {document_kind}")
        require_keys(
            coordinate,
            {"start", "end", "scalar_start", "scalar_end"},
            f"{context} coordinate",
        )
        start, end = coordinate["start"], coordinate["end"]
        scalar_start, scalar_end = coordinate["scalar_start"], coordinate["scalar_end"]
        size = fixture["bytes"]
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start <= end <= size
        ):
            raise CorpusError(f"{context} has an invalid decoded-text byte range")
        if (
            not isinstance(scalar_start, int)
            or not isinstance(scalar_end, int)
            or not 0 <= scalar_start <= scalar_end
        ):
            raise CorpusError(f"{context} has an invalid decoded-text scalar range")
        projected_text = match["value"]
        if isinstance(projected_text, dict):
            require_keys(projected_text, {"text", "captures"}, f"{context} text projection")
            captures = projected_text["captures"]
            if not isinstance(captures, dict) or not all(
                isinstance(name, str) and isinstance(value, str)
                for name, value in captures.items()
            ):
                raise CorpusError(f"{context} captures must map names to text")
            projected_text = projected_text["text"]
        if not isinstance(projected_text, str):
            raise CorpusError(f"{context} decoded-text projection must contain text")
        if fixture_bytes is not None:
            try:
                text_before = fixture_bytes[:start].decode("utf-8")
                text_match = fixture_bytes[start:end].decode("utf-8")
                text_through = fixture_bytes[:end].decode("utf-8")
            except UnicodeDecodeError as error:
                raise CorpusError(f"{context} range does not align with UTF-8") from error
            if len(text_before) != scalar_start or len(text_through) != scalar_end:
                raise CorpusError(f"{context} scalar range does not match its UTF-8 byte range")
            if text_match != projected_text:
                raise CorpusError(f"{context} value does not equal its decoded-text range")
    elif kind == "json_pointer":
        if document_kind != "json":
            raise CorpusError(f"{context} JSON Pointer is invalid for {document_kind}")
        pointer = coordinate.get("pointer")
        value = load_json(fixture_path)
        if not isinstance(pointer, str) or resolve_pointer(value, pointer) != match["value"]:
            raise CorpusError(f"{context} value does not equal its JSON Pointer target")
    elif document_kind == "dom":
        epoch, node_ids = load_node_fixture(fixture_path, "dom")
        if (
            set(coordinate) != {"document_epoch", "node_id"}
            or coordinate.get("document_epoch") != epoch
            or not _positive_u64(coordinate.get("node_id"))
            or coordinate.get("node_id") not in node_ids
        ):
            raise CorpusError(f"{context} does not name a canonical DOM coordinate")
    elif kind == "document_node":
        if document_kind != "ax":
            raise CorpusError(f"{context} node coordinate is invalid for {document_kind}")
        epoch, node_ids = load_node_fixture(fixture_path, "ax")
        if coordinate.get("document_epoch") != epoch or coordinate.get("node_id") not in node_ids:
            raise CorpusError(f"{context} does not name a node in the bound document epoch")
    else:
        raise CorpusError(f"{context} has unknown coordinate kind: {kind!r}")


def case_pairs(cases: list[Any], label: str) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    ids: set[str] = set()
    for index, case in enumerate(cases):
        context = f"{label} case #{index}"
        if not isinstance(case, dict):
            raise CorpusError(f"{context} must be an object")
        locator = case.get("locator")
        projection = case.get("projection")
        if not isinstance(locator, dict) or not isinstance(projection, dict):
            raise CorpusError(f"{context} locator and projection must be objects")
        pair = (case.get("document_kind"), locator.get("kind"))
        case_id = case.get("id")
        if case_id in ids:
            raise CorpusError(f"duplicate {label} case id: {case_id}")
        if pair in pairs:
            raise CorpusError(f"duplicate {label} pair: {pair}")
        ids.add(case_id)
        pairs.add(pair)
        expected_contract = SUPPORTED_CASES.get(case_id)
        actual_contract = (pair[0], pair[1], projection.get("kind"))
        if expected_contract != actual_contract:
            raise CorpusError(
                f"{context} contract mismatch: expected {expected_contract}, got {actual_contract}"
            )
    if ids != set(SUPPORTED_CASES):
        raise CorpusError(f"{label} case ids do not match the supported registry")
    return pairs


def validate_matrix(
    root: Path,
    matrix: dict[str, Any],
    fixtures: dict[str, dict[str, Any]],
    advanced_fixtures: dict[str, dict[str, Any]],
    advanced_directory: Path | None,
) -> None:
    if matrix.get("schema") != MATRIX_SCHEMA:
        raise CorpusError(f"unsupported matrix schema: {matrix.get('schema')!r}")
    if matrix.get("phases") != ["plan_compile", "parse", "locate", "materialize", "end_to_end"]:
        raise CorpusError(
            "matrix phases must cover compilation, parsing, locating, materialization, and evaluation"
        )
    expected_benchmarks = [
        {
            "document_kind": document_kind,
            "fixture_id": fixture_id,
            "phase": phase,
            "criterion_id": criterion_id,
        }
        for document_kind, fixture_id, phase, criterion_id in BENCHMARK_REGISTRY
    ]
    if matrix.get("benchmark_cases") != expected_benchmarks:
        raise CorpusError(
            "benchmark ID registry must cover every document-locator harness phase"
        )
    golden_cases = matrix.get("golden_cases")
    region_cases = matrix.get("region_cases")
    advanced_cases = matrix.get("advanced_cases")
    if (
        not isinstance(golden_cases, list)
        or not isinstance(region_cases, list)
        or not isinstance(advanced_cases, list)
    ):
        raise CorpusError("matrix case collections must be lists")
    if case_pairs(golden_cases, "golden") != SUPPORTED_PAIRS:
        raise CorpusError("golden cases do not cover exactly the supported locator pairs")
    if case_pairs(advanced_cases, "advanced") != SUPPORTED_PAIRS:
        raise CorpusError("advanced cases do not cover exactly the supported locator pairs")

    for case in golden_cases:
        context = f"golden case {case['id']}"
        require_keys(
            case,
            {"id", "document_kind", "fixture_id", "locator", "projection", "output_id", "expected"},
            context,
        )
        fixture = fixtures.get(case["fixture_id"])
        if fixture is None or fixture["document_kind"] != case["document_kind"]:
            raise CorpusError(f"{context} references an incompatible fixture")
        if not isinstance(case["output_id"], str) or not case["output_id"]:
            raise CorpusError(f"{context} needs an exact output id")
        expected = case["expected"]
        if not isinstance(expected, dict) or not isinstance(expected.get("matches"), list):
            raise CorpusError(f"{context} expected result must be an object with matches")
        if expected.get("match_count") != len(expected["matches"]):
            raise CorpusError(f"{context} match count does not match ordered values")
        fixture_path = root / fixture["path"]
        fixture_bytes = fixture_path.read_bytes() if fixture_path.is_file() else None
        for index, match in enumerate(expected["matches"]):
            if not isinstance(match, dict):
                raise CorpusError(f"{context} match #{index} must be an object")
            validate_expected_match(
                root,
                fixture,
                match,
                f"{context} match #{index}",
                fixture_bytes=fixture_bytes,
            )
        try:
            validate_case(root / fixture["path"], fixture["document_kind"], case)
        except OracleError as error:
            raise CorpusError(f"{context} semantic oracle failed: {error}") from error

    if not all(isinstance(case, dict) for case in region_cases):
        raise CorpusError("golden region cases must be objects")
    if [case["id"] for case in region_cases] != ["html_product_regions"]:
        raise CorpusError("golden region cases must lock the repeated HTML product example")
    for case in region_cases:
        context = f"golden region case {case.get('id')}"
        require_keys(
            case,
            {
                "id",
                "document_kind",
                "fixture_id",
                "region",
                "expected_region_count",
                "outputs",
            },
            context,
        )
        if case["document_kind"] != "html":
            raise CorpusError(f"{context} must use source HTML")
        fixture = fixtures.get(case["fixture_id"])
        if fixture is None or fixture["document_kind"] != "html":
            raise CorpusError(f"{context} references an incompatible fixture")
        region = case["region"]
        if not isinstance(region, dict):
            raise CorpusError(f"{context} region must be an object")
        require_keys(region, {"id", "locator"}, f"{context} region")
        if not isinstance(region["locator"], dict) or not isinstance(region["id"], str):
            raise CorpusError(f"{context} region identity and locator must be typed")
        if not isinstance(case["outputs"], list) or not case["outputs"]:
            raise CorpusError(f"{context} needs at least one output")
        for output in case["outputs"]:
            if not isinstance(output, dict):
                raise CorpusError(f"{context} outputs must be objects")
            require_keys(output, {"output_id", "locator", "projection", "expected"}, context)
            if (
                not isinstance(output["output_id"], str)
                or not output["output_id"]
                or not isinstance(output["locator"], dict)
                or not isinstance(output["projection"], dict)
            ):
                raise CorpusError(f"{context} output identity, locator, and projection must be typed")
            expected = output["expected"]
            if not isinstance(expected, dict) or not isinstance(expected.get("matches"), list):
                raise CorpusError(f"{context} output expected result needs ordered matches")
            if expected.get("match_count") != len(expected["matches"]):
                raise CorpusError(f"{context} output count does not match its expected values")
        try:
            validate_html_region_case(root / fixture["path"], case)
        except OracleError as error:
            raise CorpusError(f"{context} semantic oracle failed: {error}") from error

    for case in advanced_cases:
        context = f"advanced case {case['id']}"
        require_keys(
            case,
            {
                "id",
                "document_kind",
                "fixture_id",
                "locator",
                "projection",
                "owner_issue",
                "expectation_state",
                "expected",
            },
            context,
        )
        fixture = advanced_fixtures.get(case["fixture_id"])
        if fixture is None or fixture["document_kind"] != case["document_kind"]:
            raise CorpusError(f"{context} references an incompatible fixture")
        expected = case["expected"]
        expected_owners = {
            "html": "CAS-389",
            "xml": "CAS-390",
            "json": "CAS-388",
            "dom": "CAS-392",
            "ax": "CAS-391",
            "text": "CAS-387",
        }
        if case["owner_issue"] != expected_owners.get(case["document_kind"]):
            raise CorpusError(f"{context} owner does not match its document modality")
        if expected is None:
            raise CorpusError(f"{context} advanced expectation must be locked")
        if not isinstance(expected, dict):
            raise CorpusError(f"{context} expected value must be an object")
        locator = case["locator"]
        projection = case["projection"]
        if not isinstance(locator, dict) or not isinstance(projection, dict):
            raise CorpusError(f"{context} locator and projection must be objects")
        if not isinstance(locator.get("expression"), str):
            raise CorpusError(f"{context} locator expression must be text")
        document_kind = case["document_kind"]
        fixture_path = (advanced_directory or root) / fixture["path"]
        fixture_bytes = fixture_path.read_bytes() if fixture_path.is_file() else None

        if document_kind in {"text", "xml", "ax"}:
            required_state = (
                "locked"
                if document_kind == "text"
                else f"locked-by-{case['owner_issue']}"
                if document_kind == "ax"
                else None
            )
            state = case["expectation_state"]
            if required_state is not None and state != required_state:
                raise CorpusError(f"{context} must identify its locked oracle state")
            if document_kind == "xml" and not str(state).startswith("verified-"):
                raise CorpusError(f"{context} must identify independent XML verification")
            require_keys(expected, {"match_count", "matches"}, context)
            matches = expected["matches"]
            if not isinstance(matches, list) or expected["match_count"] != len(matches):
                raise CorpusError(f"{context} match count does not match ordered values")
            if document_kind == "ax":
                completeness = expected.get("completeness")
                if not isinstance(completeness, dict) or completeness.get("status") not in {
                    "complete",
                    "partial",
                    "unknown",
                }:
                    raise CorpusError(f"{context} needs an exact AX completeness state")
            for index, match in enumerate(matches):
                match_context = f"{context} match #{index}"
                if not isinstance(match, dict):
                    raise CorpusError(f"{match_context} must be an object")
                if document_kind == "ax":
                    coordinate = match.get("coordinate")
                    if (
                        not isinstance(coordinate, dict)
                        or set(coordinate) != {"document_epoch", "node_id", "kind"}
                        or coordinate.get("kind") != "document_node"
                        or type(coordinate.get("document_epoch")) is not int
                        or coordinate["document_epoch"] <= 0
                        or not isinstance(coordinate.get("node_id"), str)
                        or not coordinate["node_id"].strip()
                    ):
                        raise CorpusError(f"{match_context} has an invalid AX coordinate")
                    if projection.get("kind") == "node_reference" and match.get("value") != {
                        "document_epoch": coordinate["document_epoch"],
                        "node_id": coordinate["node_id"],
                    }:
                        raise CorpusError(f"{match_context} node value differs from its coordinate")
                    if projection.get("kind") == "text" and not isinstance(match.get("value"), str):
                        raise CorpusError(f"{match_context} text projection must be text")
                else:
                    validate_expected_match(
                        root,
                        fixture,
                        match,
                        match_context,
                        fixture_root=advanced_directory or root,
                        fixture_bytes=fixture_bytes,
                    )
            if document_kind == "xml":
                namespace_bindings = locator.get("namespace_bindings", {})
                if not isinstance(namespace_bindings, dict) or not all(
                    isinstance(prefix, str)
                    and isinstance(uri, str)
                    and uri.strip()
                    for prefix, uri in namespace_bindings.items()
                ):
                    raise CorpusError(f"{context} namespace bindings must map prefixes to URIs")
            if fixture_bytes is not None:
                try:
                    validate_case(fixture_path, document_kind, case)
                except OracleError as error:
                    raise CorpusError(f"{context} semantic oracle failed: {error}") from error
            if document_kind == "ax" and fixture_bytes is not None:
                load_node_fixture(fixture_path, "ax")
        elif document_kind == "json":
            if case["expectation_state"] != "locked-exact-json-oracle":
                raise CorpusError(f"{context} must identify its exact JSON oracle state")
            validate_locked_json_expectation(case, expected, context)
        elif document_kind == "html":
            if case["expectation_state"] != "locked-independent-lxml-reference":
                raise CorpusError(f"{context} must identify its locked HTML reference state")
            require_keys(
                expected,
                {"reference", "match_count", "records_sha256", "first", "last"},
                context,
            )
            reference = expected["reference"]
            require_keys(
                reference,
                {"parser", "lxml_version", "libxml2_version", "encoding", "network"},
                f"{context} reference",
            )
            if (
                reference["parser"] != "lxml.etree.HTMLParser"
                or reference["encoding"] != "strict-utf8"
                or reference["network"] != "disabled"
                or not isinstance(reference["lxml_version"], str)
                or not reference["lxml_version"]
                or not isinstance(reference["libxml2_version"], str)
                or not reference["libxml2_version"]
            ):
                raise CorpusError(f"{context} has an incomplete independent parser identity")
            count = expected["match_count"]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise CorpusError(f"{context} has an invalid match count")
            digest = expected["records_sha256"]
            if not isinstance(digest, str) or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise CorpusError(f"{context} needs a lowercase SHA-256 record digest")
            for sample_name in ("first", "last"):
                samples = expected[sample_name]
                if not isinstance(samples, list) or len(samples) != min(3, count):
                    raise CorpusError(f"{context} {sample_name} sample count is invalid")
                for index, sample in enumerate(samples):
                    validate_expected_match(
                        root,
                        fixture,
                        sample,
                        f"{context} {sample_name} sample #{index}",
                        fixture_root=advanced_directory or root,
                    )
        elif document_kind == "dom":
            if case["expectation_state"] != "locked-normalized-rendered-dom-oracle":
                raise CorpusError(f"{context} must identify its locked rendered-DOM oracle state")
            require_keys(
                expected,
                {"reference", "match_count", "records_sha256", "first", "last"},
                context,
            )
            normalized_entry = advanced_fixtures.get("advanced-wcag-rendered-dom-v1")
            raw_entry = advanced_fixtures.get("advanced-wcag-dom-snapshot")
            if normalized_entry is None or raw_entry is None:
                raise CorpusError(f"{context} has no raw and normalized DOM manifest entries")
            if case["fixture_id"] != "advanced-wcag-rendered-dom-v1":
                raise CorpusError(f"{context} must query the normalized DOM fixture")
            normalization = normalized_entry["provenance"]["normalization"]
            reference = expected["reference"]
            if not isinstance(reference, dict):
                raise CorpusError(f"{context} reference identity must be an object")
            reference_keys = {
                "source_fixture_id",
                "source_sha256",
                "normalizer_id",
                "normalizer_version",
                "schema",
                "normalized_sha256",
            }
            require_keys(reference, reference_keys, f"{context} reference")
            if set(reference) != reference_keys or reference != {
                "source_fixture_id": "advanced-wcag-dom-snapshot",
                "source_sha256": raw_entry["sha256"],
                "normalizer_id": normalization["id"],
                "normalizer_version": normalization["version"],
                "schema": normalized_entry["schema_identity"],
                "normalized_sha256": normalized_entry["sha256"],
            }:
                raise CorpusError(f"{context} reference does not match pinned normalization provenance")
            count = expected["match_count"]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise CorpusError(f"{context} has an invalid match count")
            digest = expected["records_sha256"]
            if not isinstance(digest, str) or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise CorpusError(f"{context} needs a lowercase SHA-256 record digest")
            for sample_name in ("first", "last"):
                samples = expected[sample_name]
                if not isinstance(samples, list) or len(samples) != min(3, count):
                    raise CorpusError(f"{context} {sample_name} sample count is invalid")
                for index, sample in enumerate(samples):
                    sample_context = f"{context} {sample_name} sample #{index}"
                    require_keys(sample, {"value", "coordinate"}, sample_context)
                    coordinate = sample["coordinate"]
                    if (
                        not isinstance(coordinate, dict)
                        or set(coordinate) != {"document_epoch", "node_id"}
                        or coordinate.get("document_epoch") != normalization["document_epoch"]
                        or not _positive_u64(coordinate.get("node_id"))
                    ):
                        raise CorpusError(f"{sample_context} has an invalid DOM coordinate")
                    if projection.get("kind") == "node_reference":
                        if sample["value"] != coordinate:
                            raise CorpusError(f"{sample_context} node reference differs from its coordinate")
                    elif not isinstance(sample["value"], str):
                        raise CorpusError(f"{sample_context} projection must be text")
        else:
            raise CorpusError(f"{context} has unsupported document kind {document_kind!r}")


def validate_locked_json_expectation(
    case: dict[str, Any], expected: Any, context: str
) -> None:
    if not isinstance(expected, dict):
        raise CorpusError(f"{context} locked expectation must be an object")
    if case["locator"].get("kind") == "json_pointer":
        require_keys(expected, {"match_count", "matches"}, f"{context} expectation")
        matches = expected["matches"]
        if not isinstance(matches, list) or expected["match_count"] != len(matches):
            raise CorpusError(f"{context} pointer expectation has an invalid match count")
        if len(matches) != 1:
            raise CorpusError(f"{context} advanced pointer oracle must select exactly one value")
        match = matches[0]
        if not isinstance(match, dict):
            raise CorpusError(f"{context} pointer expectation must contain one match")
        require_keys(match, {"value", "coordinate"}, f"{context} pointer match")
        coordinate = match["coordinate"]
        if (
            not isinstance(coordinate, dict)
            or coordinate.get("kind") != "json_pointer"
            or coordinate.get("pointer") != case["locator"].get("expression")
        ):
            raise CorpusError(f"{context} pointer expectation has an invalid coordinate")
        return

    if case["locator"].get("kind") != "json_path":
        raise CorpusError(f"{context} locked JSON oracle uses an unsupported locator")
    require_keys(
        expected,
        {"match_count", "ordered_coordinate_sha256", "first_match", "last_match"},
        f"{context} expectation",
    )
    count = expected["match_count"]
    digest = expected["ordered_coordinate_sha256"]
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise CorpusError(f"{context} JSONPath oracle needs a positive match count")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise CorpusError(f"{context} JSONPath oracle needs a lowercase SHA-256 digest")
    for sample_name in ("first_match", "last_match"):
        sample = expected[sample_name]
        if not isinstance(sample, dict):
            raise CorpusError(f"{context} {sample_name} must be a match object")
        require_keys(sample, {"value", "coordinate"}, f"{context} {sample_name}")
        coordinate = sample["coordinate"]
        if (
            not isinstance(coordinate, dict)
            or coordinate.get("kind") != "json_pointer"
            or not isinstance(coordinate.get("pointer"), str)
        ):
            raise CorpusError(f"{context} {sample_name} has an invalid JSON coordinate")
        if not isinstance(sample.get("value"), (str, int, float, bool, type(None))):
            raise CorpusError(f"{context} {sample_name} has a non-JSON value")



def validate_advanced_manifest(
    root: Path, manifest: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") != ADVANCED_SCHEMA:
        raise CorpusError(f"unsupported advanced schema: {manifest.get('schema')!r}")
    storage = manifest.get("storage")
    if not isinstance(storage, dict) or storage.get("raw_files_tracked") is not False:
        raise CorpusError("advanced manifest must explicitly exclude materialized raw files")
    if storage.get("network_fetch") != "unsupported because several source URLs are mutable":
        raise CorpusError("advanced manifest must forbid implicit mutable-source downloads")
    artifact = storage.get("source_artifact")
    if not isinstance(artifact, dict):
        raise CorpusError("advanced manifest must name a retained source artifact")
    require_keys(
        artifact,
        {"path", "format", "bytes", "sha256", "generation"},
        "advanced source artifact",
    )
    artifact_path = safe_relative_path(artifact["path"], "advanced source artifact")
    if artifact["format"] != "tar+gzip":
        raise CorpusError("advanced source artifact must use tar+gzip")
    if not isinstance(artifact["bytes"], int) or artifact["bytes"] <= 0:
        raise CorpusError("advanced source artifact must record a positive byte count")
    if (
        not isinstance(artifact["sha256"], str)
        or len(artifact["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in artifact["sha256"])
    ):
        raise CorpusError("advanced source artifact must record a SHA-256 digest")
    if not isinstance(artifact["generation"], str) or not artifact["generation"].strip():
        raise CorpusError("advanced source artifact must record deterministic generation")
    retained_path = root / "advanced" / artifact_path
    try:
        retained_size = retained_path.stat().st_size
    except OSError as error:
        raise CorpusError(f"advanced source artifact is unavailable: {error}") from error
    if retained_size != artifact["bytes"]:
        raise CorpusError("advanced source artifact size does not match its manifest")
    try:
        retained_sha256 = hashlib.sha256(retained_path.read_bytes()).hexdigest()
    except OSError as error:
        raise CorpusError(f"advanced source artifact cannot be hashed: {error}") from error
    if retained_sha256 != artifact["sha256"]:
        raise CorpusError("advanced source artifact SHA-256 does not match its manifest")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise CorpusError("advanced manifest files must be a list")
    expanded_bytes = sum(entry.get("bytes", 0) for entry in files if isinstance(entry, dict))
    source_and_browser_bytes = sum(
        entry.get("bytes", 0)
        for entry in files
        if isinstance(entry, dict)
        and entry.get("provenance", {}).get("kind")
        not in {"derived", "normalized-derived"}
    )
    if storage.get("expanded_bytes") != expanded_bytes:
        raise CorpusError("advanced expanded byte total does not match its file manifest")
    if storage.get("source_and_browser_bytes") != source_and_browser_bytes:
        raise CorpusError("advanced source/browser byte total does not match its file manifest")
    by_id: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for index, entry in enumerate(files):
        context = f"advanced file #{index}"
        if not isinstance(entry, dict):
            raise CorpusError(f"{context} must be an object")
        require_keys(
            entry,
            {
                "id",
                "path",
                "document_kind",
                "schema_identity",
                "encoding",
                "source_url",
                "captured_at",
                "bytes",
                "sha256",
                "license",
                "provenance",
            },
            context,
        )
        relative_path = safe_relative_path(entry["path"], context)
        if entry["id"] in by_id or relative_path in paths:
            raise CorpusError(f"duplicate advanced fixture id or path: {entry['id']}")
        if entry["id"] in {"advanced-whatwg-html", "advanced-wcag-html"} and (
            entry["document_kind"] != "html" or entry["schema_identity"] != HTML_PROFILE
        ):
            raise CorpusError(f"{context} must use the static UTF-8 HTML parser profile")
        if not isinstance(entry["captured_at"], str) or not entry["captured_at"]:
            raise CorpusError(f"{context} must record a capture timestamp")
        if not isinstance(entry["bytes"], int) or isinstance(entry["bytes"], bool) or entry["bytes"] <= 0:
            raise CorpusError(f"{context} must record a positive byte count")
        digest = entry["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise CorpusError(f"{context} needs a lowercase SHA-256 digest")
        license_entry = entry["license"]
        if entry["encoding"] != "utf-8" or not isinstance(entry["provenance"], dict):
            raise CorpusError(f"{context} has invalid encoding or provenance")
        if not isinstance(license_entry, dict):
            raise CorpusError(f"{context} license must be an object")
        require_keys(
            license_entry,
            {"name", "url", "attribution", "redistribution"},
            f"{context} license",
        )
        if not all(
            isinstance(license_entry[field], str) and license_entry[field].strip()
            for field in ["name", "url", "attribution", "redistribution"]
        ):
            raise CorpusError(f"{context} license metadata must be non-empty strings")
        by_id[entry["id"]] = entry
        paths.add(relative_path)

    dom = by_id.get("advanced-wcag-dom-snapshot", {})
    rendered_dom = by_id.get("advanced-wcag-rendered-dom-v1", {})
    ax = by_id.get("advanced-wcag-accessibility-tree", {})
    if dom.get("provenance", {}).get("normalization") != f"generated-as-{DOM_SCHEMA}":
        raise CorpusError("advanced DOMSnapshot must name its canonical normalized output")
    if (
        rendered_dom.get("document_kind") != "dom"
        or rendered_dom.get("schema_identity") != DOM_SCHEMA
        or rendered_dom.get("path") != "browser/wcag22/rendered-dom-v1.json"
        or rendered_dom.get("provenance", {}).get("kind") != "normalized-derived"
        or rendered_dom.get("provenance", {}).get("derived_from") != "advanced-wcag-dom-snapshot"
    ):
        raise CorpusError("advanced canonical rendered-DOM entry has invalid source identity")
    normalization = rendered_dom.get("provenance", {}).get("normalization")
    if not isinstance(normalization, dict):
        raise CorpusError("advanced canonical rendered-DOM entry lacks normalizer metadata")
    required_normalization = {
        "id",
        "version",
        "schema",
        "source_fixture_id",
        "source_sha256",
        "document_epoch",
        "element_namespace_inference",
        "attribute_namespace_inference",
        "pseudo_element_policy",
        "tree_model",
        "exclusions",
    }
    require_keys(normalization, required_normalization, "advanced DOM normalization")
    if (
        set(normalization) != required_normalization
        or normalization.get("id") != DOM_NORMALIZER_ID
        or normalization.get("version") != DOM_NORMALIZER_VERSION
        or normalization.get("schema") != DOM_SCHEMA
        or normalization.get("source_fixture_id") != "advanced-wcag-dom-snapshot"
        or normalization.get("source_sha256") != dom.get("sha256")
        or not _positive_u64(normalization.get("document_epoch"))
        or normalization.get("tree_model") != "document_light_dom"
        or normalization.get("element_namespace_inference")
        != "whatwg-html-foreign-content-with-svg-adjusted-names-v1"
        or normalization.get("attribute_namespace_inference")
        != "foreign-elements-only-standard-xml-xmlns-xlink-prefixes-v2"
        or normalization.get("pseudo_element_policy")
        != "omit-pseudoType-index-and-double-colon-name-subtrees-v1"
        or normalization.get("exclusions")
        != [
            "shadow-dom",
            "iframe-subdocuments",
            "pseudo-elements",
            "flattened-composed-trees",
            "layout-visibility",
        ]
    ):
        raise CorpusError("advanced rendered-DOM normalizer authority is incomplete or drifted")
    if ax.get("document_kind") != "ax" or ax.get("schema_identity") != AX_SCHEMA:
        raise CorpusError("advanced AX entry must use the provider-neutral v1 schema")
    if ax.get("provenance", {}).get("normalization") != AX_SCHEMA:
        raise CorpusError("advanced AX tree must declare its provider-neutral v1 schema")
    return by_id


def validate_materialized(
    directory: Path,
    fixtures: dict[str, dict[str, Any]],
    required: bool,
) -> None:
    present = [entry for entry in fixtures.values() if (directory / entry["path"]).is_file()]
    if not present and not required:
        return
    if len(present) != len(fixtures):
        missing = sorted(
            entry["path"] for entry in fixtures.values() if not (directory / entry["path"]).is_file()
        )
        raise CorpusError(f"advanced corpus is partial; missing: {', '.join(missing)}")
    for entry in fixtures.values():
        validate_file(directory / entry["path"], entry, f"advanced fixture {entry['id']}")
        if entry["document_kind"] == "dom" and entry["schema_identity"] == DOM_SCHEMA:
            load_node_fixture(directory / entry["path"], "dom")


def validate_corpus(
    root: Path,
    *,
    manifest: dict[str, Any] | None = None,
    matrix: dict[str, Any] | None = None,
    advanced_manifest: dict[str, Any] | None = None,
    advanced_directory: Path | None = None,
    require_advanced: bool = False,
) -> None:
    manifest = manifest or load_json(root / "manifest.json")
    matrix = matrix or load_json(root / "matrix.json")
    advanced_manifest = advanced_manifest or load_json(root / "advanced/manifest.json")
    fixtures = validate_manifest(root, manifest)
    advanced_fixtures = validate_advanced_manifest(root, advanced_manifest)
    materialized = advanced_directory or root / "advanced/materialized"
    validate_matrix(root, matrix, fixtures, advanced_fixtures, materialized)
    validate_materialized(materialized, advanced_fixtures, require_advanced)
    if all((materialized / entry["path"]).is_file() for entry in advanced_fixtures.values()):
        validate_locked_advanced_json_cases(matrix, advanced_fixtures, materialized)
        html_path = materialized / advanced_fixtures["advanced-whatwg-html"]["path"]
        for case in matrix["advanced_cases"]:
            if case["document_kind"] != "html":
                continue
            try:
                validate_advanced_html_case(html_path, case, case["expected"])
            except OracleError as error:
                raise CorpusError(
                    f"advanced case {case['id']} semantic oracle failed: {error}"
                ) from error
        rendered_dom = advanced_fixtures["advanced-wcag-rendered-dom-v1"]
        rendered_path = materialized / rendered_dom["path"]
        for case in matrix["advanced_cases"]:
            if case["owner_issue"] != "CAS-392" or case["document_kind"] != "dom":
                continue
            try:
                validate_advanced_dom_case(rendered_path, case, case["expected"])
            except OracleError as error:
                raise CorpusError(
                    f"advanced case {case['id']} semantic oracle failed: {error}"
                ) from error


def validate_locked_advanced_json_cases(
    matrix: dict[str, Any],
    advanced_fixtures: dict[str, dict[str, Any]],
    materialized: Path,
) -> None:
    for case in matrix["advanced_cases"]:
        if case["document_kind"] != "json":
            continue
        fixture = advanced_fixtures[case["fixture_id"]]
        path = materialized / fixture["path"]
        document = json_document(path)
        expression = case["locator"]["expression"]
        try:
            if case["locator"]["kind"] == "json_pointer":
                selected = json_pointer_result(document, expression)
                expected_matches = [
                    (match["coordinate"]["pointer"], match["value"])
                    for match in case["expected"]["matches"]
                ]
                if selected != expected_matches or len(selected) != case["expected"]["match_count"]:
                    raise CorpusError(
                        f"advanced case {case['id']} disagrees with its exact oracle"
                    )
                continue
            if case["locator"]["kind"] != "json_path":
                raise CorpusError(f"advanced case {case['id']} has an unsupported JSON locator")
            selected = json_path_results(document, expression)
        except OracleError as error:
            raise CorpusError(f"advanced case {case['id']} has an invalid JSON query") from error
        expected = case["expected"]
        digest = hashlib.sha256(
            "".join(f"{pointer}\n" for pointer, _ in selected).encode("utf-8")
        ).hexdigest()
        first = selected[0] if selected else None
        last = selected[-1] if selected else None
        actual_first = (
            {
                "value": first[1],
                "coordinate": {"kind": "json_pointer", "pointer": first[0]},
            }
            if first is not None
            else None
        )
        actual_last = (
            {
                "value": last[1],
                "coordinate": {"kind": "json_pointer", "pointer": last[0]},
            }
            if last is not None
            else None
        )
        if (
            len(selected) != expected["match_count"]
            or digest != expected["ordered_coordinate_sha256"]
            or actual_first != expected["first_match"]
            or actual_last != expected["last_match"]
        ):
            raise CorpusError(f"advanced case {case['id']} disagrees with its exact oracle")


def expect_rejected(action: Any, name: str) -> None:
    try:
        action()
    except CorpusError:
        return
    raise CorpusError(f"self-test failed: {name} was accepted")


def run_self_test(root: Path) -> None:
    validate_svg_tag_name_adjustments()
    manifest = load_json(root / "manifest.json")
    matrix = load_json(root / "matrix.json")
    advanced_manifest = load_json(root / "advanced/manifest.json")

    bad_schema = copy.deepcopy(manifest)
    bad_schema["schema"] = "yosoi.document-locator-corpus.v999"
    expect_rejected(
        lambda: validate_corpus(
            root, manifest=bad_schema, matrix=matrix, advanced_manifest=advanced_manifest
        ),
        "unknown corpus schema",
    )

    bad_digest = copy.deepcopy(manifest)
    bad_digest["files"][0]["sha256"] = "0" * 64
    expect_rejected(
        lambda: validate_corpus(
            root, manifest=bad_digest, matrix=matrix, advanced_manifest=advanced_manifest
        ),
        "fixture digest mismatch",
    )

    bad_archive_digest = copy.deepcopy(advanced_manifest)
    bad_archive_digest["storage"]["source_artifact"]["sha256"] = "0" * 64
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=matrix,
            advanced_manifest=bad_archive_digest,
        ),
        "advanced archive digest mismatch",
    )

    escaping_path = copy.deepcopy(manifest)
    escaping_path["files"][0]["path"] = "../outside-corpus.html"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=escaping_path,
            matrix=matrix,
            advanced_manifest=advanced_manifest,
        ),
        "path escaping the corpus root",
    )

    bad_matrix = copy.deepcopy(matrix)
    bad_matrix["schema"] = "yosoi.document-locator-matrix.v999"
    expect_rejected(
        lambda: validate_corpus(
            root, manifest=manifest, matrix=bad_matrix, advanced_manifest=advanced_manifest
        ),
        "unknown matrix schema",
    )

    malformed_locked_oracle = copy.deepcopy(matrix)
    json_path_case = next(
        case
        for case in malformed_locked_oracle["advanced_cases"]
        if case.get("id") == "json_path"
    )
    json_path_case["expected"]["ordered_coordinate_sha256"] = "not-a-digest"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=malformed_locked_oracle,
            advanced_manifest=advanced_manifest,
        ),
        "malformed locked JSONPath advanced oracle",
    )

    wrong_html_path = copy.deepcopy(matrix)
    wrong_html_path["golden_cases"][0]["expected"]["matches"][0]["coordinate"][
        "child_path"
    ][0] += 1
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=wrong_html_path,
            advanced_manifest=advanced_manifest,
        ),
        "HTML parser path not bound to the selected node",
    )

    wrong_xml_value = copy.deepcopy(matrix)
    wrong_xml_value["golden_cases"][3]["expected"]["matches"][0]["value"] = "Wrong"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=wrong_xml_value,
            advanced_manifest=advanced_manifest,
        ),
        "XML value not projected from the selected node",
    )

    wrong_dom_node = copy.deepcopy(matrix)
    wrong_dom_node["golden_cases"][8]["expected"]["matches"][0]["coordinate"][
        "node_id"
    ] = "dom-2"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=wrong_dom_node,
            advanced_manifest=advanced_manifest,
        ),
        "existing DOM node not selected by the locator",
    )

    dom_fixture = load_json(root / "golden/rendered-dom.json")
    unnamespaced_element = copy.deepcopy(dom_fixture)
    unnamespaced_element["nodes"][2]["namespace_uri"] = ""
    validate_rendered_dom_fixture(unnamespaced_element, "self-test unnamespaced element")

    html_qualified_names = copy.deepcopy(dom_fixture)
    html_qualified_names["nodes"][2]["attributes"] = [
        {"namespace_uri": "", "name": "xml:lang", "value": "en"},
        {
            "namespace_uri": "",
            "name": "xmlns",
            "value": "http://www.w3.org/1999/xhtml",
        },
    ]
    validate_rendered_dom_fixture(html_qualified_names, "self-test unnamespaced HTML qnames")

    foreign_xlink = copy.deepcopy(dom_fixture)
    foreign_xlink["nodes"][2]["namespace_uri"] = "http://www.w3.org/2000/svg"
    foreign_xlink["nodes"][2]["tag_name"] = "svg"
    foreign_xlink["nodes"][2]["attributes"] = [
        {
            "namespace_uri": "http://www.w3.org/1999/xlink",
            "name": "href",
            "value": "https://example.test/",
        }
    ]
    validate_rendered_dom_fixture(foreign_xlink, "self-test foreign xlink local name")
    bad_foreign_xlink = copy.deepcopy(foreign_xlink)
    bad_foreign_xlink["nodes"][2]["attributes"][0]["name"] = "xlink:href"
    try:
        validate_rendered_dom_fixture(bad_foreign_xlink, "self-test qualified foreign attribute")
    except CorpusError:
        pass
    else:
        raise CorpusError("self-test accepted a qualified namespaced local attribute name")

    namespaced_attribute = copy.deepcopy(dom_fixture)
    button = namespaced_attribute["nodes"][2]
    button["attributes"] = [
        {
            "namespace_uri": "http://www.w3.org/1999/xlink",
            "name": "href",
            "value": "https://example.test/",
        }
    ]
    validate_rendered_dom_fixture(namespaced_attribute, "self-test namespaced attribute")
    dom_nodes = node_order(namespaced_attribute)
    if dom_attribute_value(button, "href") is not None:
        raise CorpusError("self-test matched a namespaced-only attribute as unprefixed")
    if locate_dom(
        namespaced_attribute,
        dom_nodes,
        {"kind": "xpath", "expression": "//button[@href]"},
    ):
        raise CorpusError("self-test selected a namespaced-only attribute with an unprefixed XPath")

    wrong_ax_value = copy.deepcopy(matrix)
    wrong_ax_value["golden_cases"][12]["expected"]["matches"][0]["value"] = "Wrong"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=wrong_ax_value,
            advanced_manifest=advanced_manifest,
        ),
        "AX value not projected from the selected node",
    )

    missing_pointer = copy.deepcopy(matrix)
    missing_pointer["golden_cases"][6]["locator"]["expression"] = "/missing"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=missing_pointer,
            advanced_manifest=advanced_manifest,
        ),
        "JSON Pointer query that does not select the expected coordinate",
    )

    missing_json_path = copy.deepcopy(matrix)
    missing_json_path["golden_cases"][7]["locator"]["expression"] = "$.missing[*]"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=missing_json_path,
            advanced_manifest=advanced_manifest,
        ),
        "JSONPath query that does not select the expected coordinates",
    )

    missing_literal = copy.deepcopy(matrix)
    missing_literal["golden_cases"][13]["locator"]["expression"] = "NOTHING"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=missing_literal,
            advanced_manifest=advanced_manifest,
        ),
        "literal text query that does not select the expected ranges",
    )

    missing_regex = copy.deepcopy(matrix)
    missing_regex["golden_cases"][14]["locator"]["expression"] = "NOTHING"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=missing_regex,
            advanced_manifest=advanced_manifest,
        ),
        "regex that does not select the expected ranges and captures",
    )

    missing_ax_coordinate_kind = copy.deepcopy(matrix)
    ax_role = next(
        (case for case in missing_ax_coordinate_kind["advanced_cases"] if case["id"] == "ax_role"),
        None,
    )
    if ax_role is None:
        raise CorpusError("self-test fixture is missing the advanced AX role case")
    role_matches = ax_role["expected"]["matches"]
    if not role_matches:
        raise CorpusError("self-test fixture has no locked AX role matches")
    role_matches[0]["coordinate"].pop("kind", None)
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=missing_ax_coordinate_kind,
            advanced_manifest=advanced_manifest,
        ),
        "advanced AX coordinate missing its document-node kind",
    )

    wrong_ax_coordinate_kind = copy.deepcopy(matrix)
    ax_role = next(
        (case for case in wrong_ax_coordinate_kind["advanced_cases"] if case["id"] == "ax_role"),
        None,
    )
    if ax_role is None:
        raise CorpusError("self-test fixture is missing the advanced AX role case")
    role_matches = ax_role["expected"]["matches"]
    if not role_matches:
        raise CorpusError("self-test fixture has no locked AX role matches")
    role_matches[0]["coordinate"]["kind"] = "accessibility"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=wrong_ax_coordinate_kind,
            advanced_manifest=advanced_manifest,
        ),
        "advanced AX coordinate with the wrong native kind",
    )

    wrong_regex_capture = copy.deepcopy(matrix)
    wrong_regex_capture["golden_cases"][14]["expected"]["matches"][0]["value"][
        "captures"
    ]["term"] = "wrong"
    expect_rejected(
        lambda: validate_corpus(
            root,
            manifest=manifest,
            matrix=wrong_regex_capture,
            advanced_manifest=advanced_manifest,
        ),
        "regex capture that does not equal the independent engine result",
    )


def derive_advanced_dom_oracles(
    root: Path,
    matrix: dict[str, Any],
    advanced_manifest: dict[str, Any],
    directory: Path,
) -> None:
    fixtures = validate_advanced_manifest(root, advanced_manifest)
    validate_materialized(directory, fixtures, required=True)
    rendered_dom = fixtures["advanced-wcag-rendered-dom-v1"]
    raw_dom = fixtures["advanced-wcag-dom-snapshot"]
    normalization = rendered_dom["provenance"]["normalization"]
    output: list[dict[str, Any]] = []
    for case in matrix["advanced_cases"]:
        if case["owner_issue"] != "CAS-392" or case["document_kind"] != "dom":
            continue
        path = directory / rendered_dom["path"]
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise OracleError("normalized DOM fixture is not an object")
            records = document_node_records("dom", document, case)
        except (OSError, UnicodeError, json.JSONDecodeError, OracleError) as error:
            raise CorpusError(f"cannot derive {case['id']} DOM oracle: {error}") from error
        count = min(3, len(records))
        output.append(
            {
                "id": case["id"],
                "expectation_state": "locked-normalized-rendered-dom-oracle",
                "expected": {
                    "reference": {
                        "source_fixture_id": "advanced-wcag-dom-snapshot",
                        "source_sha256": raw_dom["sha256"],
                        "normalizer_id": normalization["id"],
                        "normalizer_version": normalization["version"],
                        "schema": rendered_dom["schema_identity"],
                        "normalized_sha256": rendered_dom["sha256"],
                    },
                    "match_count": len(records),
                    "records_sha256": canonical_records_sha256(records),
                    "first": records[:count],
                    "last": records[-count:] if count else [],
                },
            }
        )
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


def default_root() -> Path:
    return Path(__file__).resolve().parents[2] / "benchmarks/fixtures/document-locators/v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--advanced-dir", type=Path)
    parser.add_argument("--require-advanced", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--derive-advanced-dom-oracles", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.derive_advanced_dom_oracles:
            if arguments.self_test or arguments.require_advanced:
                raise CorpusError("oracle derivation cannot be combined with validation flags")
            root = arguments.root
            advanced_manifest = load_json(root / "advanced/manifest.json")
            matrix = load_json(root / "matrix.json")
            directory = arguments.advanced_dir or root / "advanced/materialized"
            derive_advanced_dom_oracles(root, matrix, advanced_manifest, directory)
        else:
            validate_corpus(
                arguments.root,
                advanced_directory=arguments.advanced_dir,
                require_advanced=arguments.require_advanced,
            )
            if arguments.self_test:
                run_self_test(arguments.root)
    except CorpusError as error:
        print(f"document-locator corpus invalid: {error}", file=sys.stderr)
        return 1
    print("document-locator corpus verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
