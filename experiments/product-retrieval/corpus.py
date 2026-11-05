"""Build a deterministic product retrieval corpus from immutable Archive DOMs."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

SOURCE_IDS = tuple(f"obj-{number:03}" for number in range(1, 7))
REFERENCE_IDS = ["obj-001", "obj-002"]
FIELD_NAMES = ("id", "name", "price", "color", "material", "stock")
MAX_DOM_NODES = 20_000
MAX_DOM_DEPTH = 256
MAX_CANDIDATES = 5_000
MAX_CANDIDATE_TEXT = 4_096
MAX_ATTRIBUTE_TEXT = 2_048
_IGNORED_TEXT_TAGS = {"script", "style", "noscript", "template"}

_VARIANTS = (
    "class_rename",
    "label_paraphrase",
    "field_reorder",
    "missing_field",
    "recommendation_decoys",
    "multiple_price_roles",
    "alternate_layout",
    "repeated_nested_products",
    "value_permutation",
)


def prepare_corpus(source_dir: str | Path) -> dict[str, Any]:
    """Return original Archive cases and independently mutated control cases.

    Candidate generation reads only each rendered DOM document. Gold annotations
    are built separately from the original fixture markup and mutation bookkeeping.
    The source Archive files are read and verified but never modified.
    """
    evidence_dir = Path(source_dir)
    archive_sources: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []

    for source_index, source_id in enumerate(SOURCE_IDS):
        document, source_info = _load_archive_document(evidence_dir, source_id)
        archive_sources.append(source_info)
        gold = _annotate_original(document)
        split = "development" if source_id in REFERENCE_IDS else "controlled"

        cases.append(
            _build_case(
                case_id=source_id,
                source_id=source_id,
                split=split,
                variant="original",
                family="javascript_product_detail",
                document=document,
                gold=gold,
                source_info=source_info,
                mutation={},
            )
        )

        for variant in _VARIANTS:
            mutated_document = copy.deepcopy(document)
            mutated_gold = copy.deepcopy(gold)
            mutation = _apply_variant(
                mutated_document,
                mutated_gold,
                variant,
                source_index,
                source_id,
            )
            _sort_document_attributes(mutated_document)
            family = _family_for_variant(variant)
            case_id = f"{source_id}.{variant}"
            cases.append(
                _build_case(
                    case_id=case_id,
                    source_id=source_id,
                    split=split,
                    variant=variant,
                    family=family,
                    document=mutated_document,
                    gold=mutated_gold,
                    source_info=source_info,
                    mutation=mutation,
                )
            )

    return {
        "cases": cases,
        "references": list(REFERENCE_IDS),
        "provenance": {
            "format": "product-retrieval-corpus-v1",
            "archive_schema": "yosoi_rendered_dom_v1",
            "source_count": len(archive_sources),
            "source_checksums": archive_sources,
            "mutation_variants": list(_VARIANTS),
            "mutation_policy": (
                "Each variant is derived independently from its "
                "immutable source capture."
            ),
            "split_policy": (
                "obj-001 and obj-002 are development references; "
                "obj-003 through obj-006 are controlled sources."
            ),
        },
    }


def build_candidates(document: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    """Generate bounded, unlabeled text, attribute, and region candidates."""
    index = _index_document(document)
    nodes = index["nodes"]
    order = index["order"]
    excluded = index["excluded"]
    text_by_id = index["text"]

    candidates: list[dict[str, Any]] = []
    for node_id in order:
        node = nodes[node_id]
        if node.get("kind") != "element" or excluded[node_id]:
            continue

        node_text = text_by_id[node_id]
        if len(node_text) <= MAX_CANDIDATE_TEXT:
            candidates.append(
                _candidate(
                    case_id,
                    len(candidates),
                    node_id,
                    "text",
                    node_text,
                    document,
                    index,
                )
            )
            if len(candidates) >= MAX_CANDIDATES:
                return candidates

        for attribute in node.get("attributes", []):
            name = str(attribute.get("name", ""))
            value = _normalize(str(attribute.get("value", "")))
            if not name or name.lower().startswith("on") or not value:
                continue
            if len(value) > MAX_ATTRIBUTE_TEXT:
                continue
            candidates.append(
                _candidate(
                    case_id,
                    len(candidates),
                    node_id,
                    f"@{name}",
                    value,
                    document,
                    index,
                )
            )
            if len(candidates) >= MAX_CANDIDATES:
                return candidates

    return candidates


def _load_archive_document(
    evidence_dir: Path, source_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    ref_path = evidence_dir / f"{source_id}.ref.json"
    ref_value = json.loads(ref_path.read_text(encoding="utf-8"))
    if not isinstance(ref_value, str) or not ref_value.startswith("document:v1:"):
        raise ValueError(f"invalid Archive document reference for {source_id}")
    record_id = ref_value.rsplit(":", 1)[-1]
    if not re.fullmatch(r"[0-9a-f-]{36}", record_id):
        raise ValueError(f"invalid Archive record ID for {source_id}")

    record_path = (
        evidence_dir
        / "archive"
        / "archive"
        / "v1"
        / "records"
        / "document"
        / record_id[:2]
        / f"{record_id}.json"
    )
    record_bytes = record_path.read_bytes()
    record = json.loads(record_bytes)
    if record.get("kind") != "document" or record.get("key") != record_id:
        raise ValueError(f"Archive record identity mismatch for {source_id}")
    value = record.get("value", {})
    profile = value.get("profile", {})
    if profile.get("representation") != "rendered_dom":
        raise ValueError(f"Archive source {source_id} is not rendered DOM")
    if profile.get("schema") != "yosoi_rendered_dom_v1":
        raise ValueError(f"unsupported Archive DOM schema for {source_id}")

    payload_path = (
        evidence_dir
        / "archive"
        / "archive"
        / "v1"
        / "documents"
        / record_id[:2]
        / record_id
        / "payload.bin"
    )
    payload = payload_path.read_bytes()
    payload_sha = hashlib.sha256(payload).hexdigest()
    record_sha = str(value.get("sha256", ""))
    byte_len = value.get("byte_len")
    if len(record_sha) != 64 or not re.fullmatch(r"[0-9a-f]{64}", record_sha):
        raise ValueError(f"invalid Archive payload SHA-256 for {source_id}")
    if byte_len != len(payload):
        raise ValueError(f"Archive payload byte length mismatch for {source_id}")
    if payload_sha != record_sha:
        raise ValueError(f"Archive payload SHA-256 mismatch for {source_id}")

    archive_provenance = json.loads(
        (evidence_dir / "provenance.json").read_text(encoding="utf-8")
    )
    capture = next(
        (
            item
            for item in archive_provenance.get("captures", [])
            if item.get("id") == source_id
        ),
        None,
    )
    if capture is None or capture.get("dom_sha256") != payload_sha:
        raise ValueError(f"capture manifest SHA-256 mismatch for {source_id}")

    document = json.loads(payload)
    _index_document(document)
    return document, {
        "source_id": source_id,
        "archive_record_id": record_id,
        "archive_record_sha256": hashlib.sha256(record_bytes).hexdigest(),
        "payload_sha256": payload_sha,
        "payload_byte_len": len(payload),
    }


def _annotate_original(document: dict[str, Any]) -> dict[str, Any]:
    nodes = {node["id"]: node for node in document["nodes"]}
    root = next(
        (
            node
            for node in nodes.values()
            if node.get("kind") == "element"
            and _attributes(node).get("data-shop-part") == "product-detail"
        ),
        None,
    )
    if root is None:
        raise ValueError("source DOM has no product detail root")
    root_id = root["id"]
    descendants = _descendants(document, root_id)

    def by_class(class_name: str) -> dict[str, Any]:
        return next(
            (
                nodes[node_id]
                for node_id in descendants
                if class_name in _attributes(nodes[node_id]).get("class", "").split()
            ),
            None,
        )

    name_node = next(
        (
            nodes[node_id]
            for node_id in descendants
            if nodes[node_id].get("kind") == "element"
            and nodes[node_id].get("tag_name") == "h1"
            and _attributes(nodes[node_id]).get("id") == "product-title"
        ),
        None,
    )
    price_node = by_class("shop-detail-price")
    stock_node = by_class("shop-availability")
    if name_node is None or price_node is None or stock_node is None:
        raise ValueError("source DOM is missing a required product field")

    facts: dict[str, Any] = {}
    for node_id in descendants:
        label_node = nodes[node_id]
        if "shop-fact-label" not in _attributes(label_node).get("class", "").split():
            continue
        label = _element_text(document, node_id).casefold()
        value_node = _next_element_sibling(document, node_id)
        if (
            value_node is not None
            and "shop-fact-value" in _attributes(value_node).get("class", "").split()
        ):
            facts[label] = value_node
    if "color" not in facts or "material" not in facts:
        raise ValueError("source DOM is missing color or material facts")

    product_id = _attributes(root).get("data-product-id")
    if not product_id:
        raise ValueError("source DOM product root has no product ID")
    targets = {
        "id": (root_id, "@data-product-id"),
        "name": (name_node["id"], "text"),
        "price": (price_node["id"], "text"),
        "color": (facts["color"]["id"], "text"),
        "material": (facts["material"]["id"], "text"),
        "stock": (stock_node["id"], "text"),
    }
    return {"root_id": root_id, "targets": targets}


def _build_case(
    *,
    case_id: str,
    source_id: str,
    split: str,
    variant: str,
    family: str,
    document: dict[str, Any],
    gold: dict[str, Any],
    source_info: dict[str, Any],
    mutation: dict[str, Any],
) -> dict[str, Any]:
    candidates = build_candidates(document, case_id)
    target_values = _target_values(document, gold)
    expected: dict[str, list[str]] = {"root": []}
    for field_name in FIELD_NAMES:
        expected[field_name] = []

    for candidate in candidates:
        if (
            candidate["node_id"] == str(gold["root_id"])
            and candidate["projection"] == "text"
        ):
            expected["root"].append(candidate["id"])

    for field_name, target in gold["targets"].items():
        node_id, projection = target
        expected_value = target_values[field_name]
        if projection.startswith("@"):
            matches = [
                candidate["id"]
                for candidate in candidates
                if candidate["node_id"] == str(node_id)
                and candidate["projection"] == projection
                and candidate["text"] == expected_value
            ]
        else:
            equivalent_nodes = {node_id, *_descendants(document, node_id)}
            matches = [
                candidate["id"]
                for candidate in candidates
                if candidate["projection"] == "text"
                and candidate["node_id"] in {str(item) for item in equivalent_nodes}
                and candidate["text"] == expected_value
            ]
        if not matches:
            raise ValueError(f"gold field {field_name} has no candidate in {case_id}")
        expected[field_name] = matches

    if not expected["root"]:
        raise ValueError(f"gold root has no candidate in {case_id}")

    return {
        "id": case_id,
        "source_id": source_id,
        "split": split,
        "variant": variant,
        "family": family,
        "document": document,
        "candidates": candidates,
        "expected": expected,
        "canonical_expected": {
            "root": expected["root"],
            **{
                field: [
                    candidate["id"]
                    for candidate in candidates
                    if candidate["node_id"] == str(target[0])
                    and candidate["projection"] == target[1]
                ]
                for field, target in gold["targets"].items()
            },
        },
        "expected_values": target_values,
        "owning_root_id": str(gold["root_id"]),
        "provenance": {
            **source_info,
            "mutation": mutation,
        },
    }


def _target_values(document: dict[str, Any], gold: dict[str, Any]) -> dict[str, str]:
    nodes = {node["id"]: node for node in document["nodes"]}
    values: dict[str, str] = {}
    for field_name, (node_id, projection) in gold["targets"].items():
        node = nodes.get(node_id)
        if node is None:
            raise ValueError(f"gold node for {field_name} is missing")
        if projection.startswith("@"):
            value = _attributes(node).get(projection[1:], "")
        else:
            value = _element_text(document, node_id)
        value = _normalize(value)
        if not value:
            raise ValueError(f"gold value for {field_name} is empty")
        values[field_name] = value
    return values


def _apply_variant(
    document: dict[str, Any],
    gold: dict[str, Any],
    variant: str,
    source_index: int,
    source_id: str,
) -> dict[str, Any]:
    nodes = {node["id"]: node for node in document["nodes"]}
    root_id = gold["root_id"]

    if variant == "class_rename":
        renamed = 0
        for node in document["nodes"]:
            attrs = _attributes(node)
            if node.get("kind") == "element" and "class" in attrs:
                _set_attribute(node, "class", f"skin-{node['id']}")
                renamed += 1
        return {
            "renamed_class_count": renamed,
            "rule": "replace each class value with a node-specific opaque token",
        }

    if variant == "label_paraphrase":
        replacements = {"material": "Composition", "color": "Finish"}
        changed: dict[str, str] = {}
        for node_id in _descendants(document, root_id):
            node = nodes[node_id]
            if "shop-fact-label" not in _attributes(node).get("class", "").split():
                continue
            label = _element_text(document, node_id).casefold()
            if label in replacements:
                _replace_direct_text(document, node_id, replacements[label])
                changed[label] = replacements[label]
        return {"labels": changed}

    if variant == "field_reorder":
        facts_root = next(
            (
                node
                for node in nodes.values()
                if node.get("kind") == "element"
                and "shop-product-facts" in _attributes(node).get("class", "").split()
            ),
            None,
        )
        if facts_root is None:
            raise ValueError(f"missing product facts region in {source_id}")
        element_children = [
            child_id
            for child_id in facts_root.get("children", [])
            if nodes[child_id].get("kind") == "element"
        ]
        if len(element_children) < 2:
            raise ValueError(f"expected two fact pairs in {source_id}")
        non_elements = [
            child_id
            for child_id in facts_root.get("children", [])
            if nodes[child_id].get("kind") != "element"
        ]
        facts_root["children"] = list(reversed(element_children)) + non_elements
        return {
            "region_node_id": str(facts_root["id"]),
            "order": "reverse child elements",
        }

    if variant == "missing_field":
        missing_field = FIELD_NAMES[source_index]
        target = gold["targets"].pop(missing_field)
        if missing_field == "id":
            _remove_attribute(nodes[root_id], "data-product-id")
        elif missing_field in {"color", "material"}:
            value_node_id = target[0]
            label_node_id = _paired_fact_label(document, value_node_id)
            _remove_subtree(document, label_node_id)
            _remove_subtree(document, value_node_id)
        else:
            _remove_subtree(document, target[0])
        return {
            "missing_field": missing_field,
            "rule": "remove the target field and its visible label when present",
        }

    if variant == "recommendation_decoys":
        parent_id = nodes[root_id].get("parent")
        decoy_root = _append_decoy_product(
            document,
            parent_id,
            product_id=f"recommendation-{source_id}",
            name="Related desk accessory",
            price="$17.50",
            color="Midnight blue",
            material="Anodized aluminum",
            stock="3 in stock and ready to find a home.",
            tag="article",
        )
        return {
            "decoy_root_id": str(decoy_root),
            "placement": "recommendation sibling of target product",
        }

    if variant == "multiple_price_roles":
        price_target = gold["targets"]["price"][0]
        price_parent_id = nodes[price_target].get("parent")
        _append_price_roles(document, price_parent_id)
        return {
            "added_roles": ["list price", "previous price"],
            "target_price_node_id": str(price_target),
        }

    if variant == "alternate_layout":
        original_values = _target_values(document, gold)
        original_id = original_values["id"]
        _clear_children(document, root_id)
        root = {node["id"]: node for node in document["nodes"]}[root_id]
        root["tag_name"] = "article"
        root["attributes"] = [
            {"namespace_uri": "", "name": "data-product-id", "value": original_id},
            {"namespace_uri": "", "name": "aria-label", "value": "Object detail"},
        ]
        _sort_attributes(root)
        header = _append_element(document, root_id, "header", {"role": "group"})
        name_node = _append_element(document, header, "h2")
        _append_text(document, name_node, original_values["name"])
        section = _append_element(
            document, root_id, "section", {"aria-label": "Specifications"}
        )
        list_node = _append_element(document, section, "dl")
        targets = {
            "id": (root_id, "@data-product-id"),
            "name": (name_node, "text"),
        }
        labels = {
            "price": "Cost",
            "material": "Composition",
            "color": "Finish",
            "stock": "Availability",
        }
        for field_name in ("price", "material", "color", "stock"):
            row = _append_element(document, list_node, "div")
            label_node = _append_element(document, row, "dt")
            _append_text(document, label_node, labels[field_name])
            value_node = _append_element(document, row, "dd")
            _append_text(document, value_node, original_values[field_name])
            targets[field_name] = (value_node, "text")
        gold["targets"] = targets
        return {"layout": "article/header/dl", "field_labels": labels}

    if variant == "repeated_nested_products":
        parent_id = nodes[root_id].get("parent")
        related = _append_element(
            document, parent_id, "section", {"class": "related-items"}
        )
        grid = _append_element(document, related, "div", {"class": "product-grid"})
        decoy_ids = []
        for ordinal, (name, price, color, material) in enumerate(
            (
                ("Desk companion", "$14.00", "Slate", "Powder-coated steel"),
                ("Everyday vessel", "$21.00", "Chalk", "Glazed stoneware"),
            ),
            start=1,
        ):
            decoy_ids.append(
                _append_decoy_product(
                    document,
                    grid,
                    product_id=f"nested-{source_id}-{ordinal}",
                    name=name,
                    price=price,
                    color=color,
                    material=material,
                    stock=f"{ordinal + 2} in stock and ready to find a home.",
                    tag="article",
                )
            )
        return {
            "wrapper_node_id": str(related),
            "nested_product_root_ids": [str(item) for item in decoy_ids],
        }

    if variant == "value_permutation":
        targets = gold["targets"]
        name_node = nodes[targets["name"][0]]
        _replace_direct_text(
            document,
            name_node["id"],
            f"{_element_text(document, name_node['id'])} Special Edition",
        )
        price_node = nodes[targets["price"][0]]
        old_price = _element_text(document, price_node["id"])
        match = re.fullmatch(r"\$([0-9]+\.[0-9]{2})", old_price)
        if match is None:
            raise ValueError(f"unexpected source price format in {source_id}")
        new_price = f"${Decimal(match.group(1)) + Decimal('7.25'):.2f}"
        _replace_direct_text(document, price_node["id"], new_price)
        return {
            "changed_values": {"name_suffix": " Special Edition", "price_delta": "7.25"}
        }

    raise ValueError(f"unsupported corpus variant: {variant}")


def _family_for_variant(variant: str) -> str:
    if variant == "alternate_layout":
        return "description_list"
    if variant in {"recommendation_decoys", "repeated_nested_products"}:
        return "multiple_product_roots"
    return "javascript_product_detail"


def _candidate(
    case_id: str,
    ordinal: int,
    node_id: Any,
    projection: str,
    text: str,
    document: dict[str, Any],
    index: dict[str, Any],
) -> dict[str, Any]:
    nodes = index["nodes"]
    parents = index["parents"]
    node = nodes[node_id]
    ancestors = _ancestor_ids(node_id, parents)
    path = _path_tags(node_id, nodes, parents)
    attributes = {
        str(attribute.get("name", "")): str(attribute.get("value", ""))
        for attribute in node.get("attributes", [])
        if attribute.get("name")
    }
    context = _local_context(node_id, document, index)
    motifs = _motifs(node_id, document, index, attributes)
    return {
        "id": f"{case_id}:candidate-{ordinal:05d}",
        "node_id": str(node_id),
        "projection": projection,
        "text": _normalize(text),
        "context": context,
        "tag": str(node.get("tag_name", "#text")),
        "attributes": attributes,
        "path": path,
        "motifs": motifs,
        "ancestors": [str(item) for item in ancestors],
    }


def _index_document(document: dict[str, Any]) -> dict[str, Any]:
    raw_nodes = document.get("nodes")
    root_id = document.get("root")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("rendered DOM has no nodes")
    nodes: dict[Any, dict[str, Any]] = {}
    for node in raw_nodes:
        if not isinstance(node, dict) or "id" not in node:
            raise ValueError("rendered DOM contains an invalid node")
        if node["id"] in nodes:
            raise ValueError("rendered DOM contains duplicate node IDs")
        nodes[node["id"]] = node
    if root_id not in nodes:
        raise ValueError("rendered DOM root ID is missing")

    parents: dict[Any, Any] = {}
    order: list[Any] = []
    excluded: dict[Any, bool] = {}
    discovered = {root_id}
    stack: list[tuple[Any, int, bool]] = [(root_id, 0, False)]
    while stack:
        node_id, depth, hidden_parent = stack.pop()
        if depth > MAX_DOM_DEPTH:
            raise ValueError("rendered DOM exceeds the candidate depth budget")
        if len(order) >= MAX_DOM_NODES:
            raise ValueError("rendered DOM exceeds the candidate node budget")
        node = nodes.get(node_id)
        if node is None:
            raise ValueError("rendered DOM references an absent child")
        order.append(node_id)
        tag = str(node.get("tag_name", "")).lower()
        is_hidden = hidden_parent or (
            node.get("kind") == "element" and tag in _IGNORED_TEXT_TAGS
        )
        excluded[node_id] = is_hidden
        children = node.get("children", [])
        for child_id in reversed(children):
            if child_id not in nodes:
                raise ValueError("rendered DOM references an absent child")
            if child_id in discovered:
                raise ValueError("rendered DOM contains a cycle or shared child")
            discovered.add(child_id)
            parents[child_id] = node_id
            stack.append((child_id, depth + 1, is_hidden))

    if len(order) != len(nodes):
        raise ValueError("rendered DOM contains nodes unreachable from its root")
    text_by_id: dict[Any, str] = {}
    for node_id in reversed(order):
        node = nodes[node_id]
        if excluded[node_id]:
            text_by_id[node_id] = ""
        elif node.get("kind") == "text":
            text_by_id[node_id] = _normalize(str(node.get("value", "")))
        elif node.get("kind") == "element":
            text_by_id[node_id] = _normalize(
                " ".join(
                    text_by_id.get(child_id, "")
                    for child_id in node.get("children", [])
                )
            )
        else:
            text_by_id[node_id] = _normalize(
                " ".join(
                    text_by_id.get(child_id, "")
                    for child_id in node.get("children", [])
                )
            )
    return {
        "nodes": nodes,
        "parents": parents,
        "order": order,
        "excluded": excluded,
        "text": text_by_id,
    }


def _ancestor_ids(node_id: Any, parents: dict[Any, Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[Any] = set()
    current = parents.get(node_id)
    while current is not None:
        if current in seen:
            raise ValueError("rendered DOM contains a cycle in parent links")
        seen.add(current)
        result.append(current)
        current = parents.get(current)
    result.reverse()
    return result


def _path_tags(
    node_id: Any, nodes: dict[Any, dict[str, Any]], parents: dict[Any, Any]
) -> list[str]:
    chain = [*_ancestor_ids(node_id, parents), node_id]
    tags = []
    for current in chain:
        node = nodes[current]
        if node.get("kind") == "element":
            tags.append(str(node.get("tag_name", "")).lower())
        elif node.get("kind") in {"document", "root"}:
            tags.append("#document")
    if not tags or tags[0] != "#document":
        tags.insert(0, "#document")
    return tags


def _local_context(
    node_id: Any, document: dict[str, Any], index: dict[str, Any]
) -> str:
    nodes = index["nodes"]
    parents = index["parents"]
    text_by_id = index["text"]
    parent_id = parents.get(node_id)
    if parent_id is None:
        return "parent=#document"
    parent = nodes[parent_id]
    siblings = parent.get("children", [])
    try:
        position = siblings.index(node_id)
    except ValueError:
        return f"parent={parent.get('tag_name', '#document')}"

    def nearby(offset: int) -> str:
        step = -1 if offset < position else 1
        cursor = offset
        while 0 <= cursor < len(siblings):
            sibling_id = siblings[cursor]
            value = text_by_id.get(sibling_id, "")
            if value:
                return value[:120]
            cursor += step
        return ""

    parent_tag = str(parent.get("tag_name", "#document"))
    pieces = [f"parent={parent_tag}"]
    before = nearby(position - 1)
    after = nearby(position + 1)
    if before:
        pieces.append(f"previous={before}")
    if after:
        pieces.append(f"next={after}")
    return " | ".join(pieces)


def _motifs(
    node_id: Any,
    document: dict[str, Any],
    index: dict[str, Any],
    attributes: dict[str, str],
) -> list[str]:
    nodes = index["nodes"]
    parents = index["parents"]
    node = nodes[node_id]
    child_tags = [
        str(nodes[child_id].get("tag_name", "")).lower()
        for child_id in node.get("children", [])
        if nodes[child_id].get("kind") == "element"
    ]
    unique_tags = sorted(set(child_tags))
    motifs = [f"child-count:{_count_bucket(len(child_tags))}"]
    motifs.append("has-text" if index["text"].get(node_id, "") else "empty-text")
    if child_tags:
        motifs.append("child-tags:" + ",".join(unique_tags[:8]))
        motifs.extend(
            f"repeat-child:{tag}" for tag in unique_tags if child_tags.count(tag) > 1
        )
    parent_id = parents.get(node_id)
    if parent_id is not None:
        parent_tag = str(nodes[parent_id].get("tag_name", "#document")).lower()
        motifs.append(f"parent-tag:{parent_tag}")
    motifs.extend(f"attribute-name:{name.lower()}" for name in sorted(attributes))
    return motifs


def _count_bucket(count: int) -> str:
    if count == 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 4:
        return "2-4"
    return "5+"


def _attributes(node: dict[str, Any]) -> dict[str, str]:
    return {
        str(attribute.get("name", "")): str(attribute.get("value", ""))
        for attribute in node.get("attributes", [])
        if attribute.get("name")
    }


def _element_text(document: dict[str, Any], node_id: Any) -> str:
    index = _index_document(document)
    return index["text"].get(node_id, "")


def _descendants(document: dict[str, Any], node_id: Any) -> list[Any]:
    nodes = {node["id"]: node for node in document["nodes"]}
    result: list[Any] = []
    stack = list(reversed(nodes[node_id].get("children", [])))
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(reversed(nodes[current].get("children", [])))
        if len(result) > MAX_DOM_NODES:
            raise ValueError("rendered DOM exceeds the annotation node budget")
    return result


def _next_element_sibling(
    document: dict[str, Any], node_id: Any
) -> dict[str, Any] | None:
    nodes = {node["id"]: node for node in document["nodes"]}
    node = nodes[node_id]
    parent = nodes.get(node.get("parent"))
    if parent is None:
        return None
    children = parent.get("children", [])
    try:
        position = children.index(node_id)
    except ValueError:
        return None
    for sibling_id in children[position + 1 :]:
        sibling = nodes[sibling_id]
        if sibling.get("kind") == "element":
            return sibling
    return None


def _paired_fact_label(document: dict[str, Any], value_node_id: Any) -> Any:
    nodes = {node["id"]: node for node in document["nodes"]}
    value_node = nodes[value_node_id]
    parent = nodes[value_node.get("parent")]
    children = [
        child_id
        for child_id in parent.get("children", [])
        if nodes[child_id].get("kind") == "element"
    ]
    position = children.index(value_node_id)
    if position == 0:
        raise ValueError("fact value has no preceding label")
    return children[position - 1]


def _replace_direct_text(document: dict[str, Any], node_id: Any, value: str) -> None:
    nodes = {node["id"]: node for node in document["nodes"]}
    node = nodes[node_id]
    for child_id in node.get("children", []):
        child = nodes[child_id]
        if child.get("kind") == "text":
            child["value"] = value
            return
    _append_text(document, node_id, value)


def _append_element(
    document: dict[str, Any],
    parent_id: Any,
    tag: str,
    attributes: dict[str, str] | None = None,
) -> int:
    nodes = {node["id"]: node for node in document["nodes"]}
    new_id = max(int(node_id) for node_id in nodes) + 1
    node = {
        "kind": "element",
        "id": new_id,
        "parent": parent_id,
        "children": [],
        "namespace_uri": "http://www.w3.org/1999/xhtml",
        "tag_name": tag,
        "attributes": sorted(
            (
                {"namespace_uri": "", "name": name, "value": value}
                for name, value in (attributes or {}).items()
            ),
            key=_attribute_sort_key,
        ),
    }
    nodes[parent_id]["children"].append(new_id)
    document["nodes"].append(node)
    return new_id


def _append_text(document: dict[str, Any], parent_id: Any, value: str) -> int:
    nodes = {node["id"]: node for node in document["nodes"]}
    new_id = max(int(node_id) for node_id in nodes) + 1
    node = {
        "kind": "text",
        "id": new_id,
        "parent": parent_id,
        "children": [],
        "value": value,
    }
    nodes[parent_id]["children"].append(new_id)
    document["nodes"].append(node)
    return new_id


def _append_decoy_product(
    document: dict[str, Any],
    parent_id: Any,
    *,
    product_id: str,
    name: str,
    price: str,
    color: str,
    material: str,
    stock: str,
    tag: str,
) -> int:
    root_id = _append_element(
        document,
        parent_id,
        tag,
        {"class": "product-card", "data-product-id": product_id},
    )
    heading = _append_element(document, root_id, "h2")
    _append_text(document, heading, name)
    price_node = _append_element(document, root_id, "p", {"aria-label": "Price"})
    _append_text(document, price_node, price)
    facts = _append_element(document, root_id, "dl")
    for label, value in (("Material", material), ("Color", color), ("Stock", stock)):
        row = _append_element(document, facts, "div")
        label_node = _append_element(document, row, "dt")
        _append_text(document, label_node, label)
        value_node = _append_element(document, row, "dd")
        _append_text(document, value_node, value)
    return root_id


def _append_price_roles(document: dict[str, Any], parent_id: Any) -> None:
    container = _append_element(
        document, parent_id, "aside", {"aria-label": "Price history"}
    )
    for label, tag, value in (
        ("List price", "del", "$129.00"),
        ("Previous price", "span", "$89.00"),
    ):
        row = _append_element(
            document,
            container,
            "p",
            {"data-price-role": label.lower().replace(" ", "-")},
        )
        label_node = _append_element(document, row, "span")
        _append_text(document, label_node, label)
        value_node = _append_element(document, row, tag)
        _append_text(document, value_node, value)


def _clear_children(document: dict[str, Any], node_id: Any) -> None:
    nodes = {node["id"]: node for node in document["nodes"]}
    node = nodes[node_id]
    remove_ids: set[Any] = set()
    stack = list(node.get("children", []))
    while stack:
        current = stack.pop()
        remove_ids.add(current)
        stack.extend(nodes[current].get("children", []))
    node["children"] = []
    document["nodes"] = [
        item for item in document["nodes"] if item["id"] not in remove_ids
    ]


def _remove_subtree(document: dict[str, Any], node_id: Any) -> None:
    nodes = {node["id"]: node for node in document["nodes"]}
    node = nodes[node_id]
    parent_id = node.get("parent")
    if parent_id is not None:
        parent = nodes[parent_id]
        parent["children"] = [
            child for child in parent.get("children", []) if child != node_id
        ]
    remove_ids: set[Any] = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        remove_ids.add(current)
        stack.extend(nodes[current].get("children", []))
    document["nodes"] = [
        item for item in document["nodes"] if item["id"] not in remove_ids
    ]


def _set_attribute(node: dict[str, Any], name: str, value: str) -> None:
    for attribute in node.get("attributes", []):
        if attribute.get("name") == name:
            attribute["value"] = value
            _sort_attributes(node)
            return
    node.setdefault("attributes", []).append(
        {"namespace_uri": "", "name": name, "value": value}
    )
    _sort_attributes(node)


def _remove_attribute(node: dict[str, Any], name: str) -> None:
    node["attributes"] = [
        attribute
        for attribute in node.get("attributes", [])
        if attribute.get("name") != name
    ]


def _sort_attributes(node: dict[str, Any]) -> None:
    node["attributes"] = sorted(
        node.get("attributes", []),
        key=_attribute_sort_key,
    )


def _sort_document_attributes(document: dict[str, Any]) -> None:
    for node in document["nodes"]:
        if node.get("kind") == "element":
            _sort_attributes(node)


def _attribute_sort_key(attribute: dict[str, Any]) -> tuple[str, str]:
    return (
        str(attribute.get("namespace_uri", "")),
        str(attribute.get("name", "")),
    )


def _normalize(value: str) -> str:
    return " ".join(value.split())
