"""Normalize manually labeled fresh product HTML pages into retrieval cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import html5lib

_RETRIEVAL_DIR = Path(__file__).resolve().parents[1]
if str(_RETRIEVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_RETRIEVAL_DIR))

from corpus import _descendants, _index_document, _normalize, build_candidates  # noqa: E402

_HTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
_FORMAT = "product-retrieval-fresh-corpus-v1"
_FIELDS = ("id", "name", "price", "color", "material", "stock")
_MAX_SOURCE_BYTES = 1_500_000


def build_fresh_corpus(fresh_dir: Path) -> dict[str, Any]:
    """Build a source-grounded corpus from captured HTML and manual labels.

    The HTML5 parser constructs a deterministic source-normalized DOM wire tree.
    This wire representation is suitable for SDK parsing, but it is not evidence
    of a live browser-rendered DOM or of client-side JavaScript execution.
    """
    fresh_dir = Path(fresh_dir)
    manifest = _read_json(fresh_dir / "manifest.json")
    labels = _read_json(fresh_dir / "labels.json")
    entries, label_by_id, failures = _validated_inputs(fresh_dir, manifest, labels)

    cases: list[dict[str, Any]] = []
    source_manifest: list[dict[str, Any]] = []
    for entry in entries:
        page_id = entry["id"]
        label = label_by_id[page_id]
        source_path = _safe_source_path(fresh_dir, entry["file"])
        payload = source_path.read_bytes()
        document = _normalize_html(payload)
        case = _build_case(page_id, entry, label, payload, document)
        cases.append(case)
        source_manifest.append(
            {
                "id": page_id,
                "site_template": entry["site_template"],
                "requested_url": entry["requested_url"],
                "final_url": entry["final_url"],
                "retrieved_at_utc": entry["retrieved_at_utc"],
                "source_html_sha256": entry["sha256"],
                "source_html_byte_len": entry["byte_len"],
                "normalized_document_sha256": _document_sha256(document),
            }
        )

    return {
        "cases": cases,
        "references": [],
        "provenance": {
            "format": _FORMAT,
            "split": "fresh_cross_site",
            "source_representation": "captured_http_response_html",
            "normalizer": {
                "library": "html5lib",
                "version": html5lib.__version__,
                "tree_builder": "etree",
                "scripting": True,
                "namespace_html_elements": True,
                "javascript_executed": False,
            },
            "document_truth": (
                "The document field is an HTML5-normalized source "
                "tree built from saved HTTP bytes. It is not a live "
                "browser-rendered DOM. Native SDK validation checks "
                "wire parsing only."
            ),
            "label_truth": labels.get("annotation_status"),
            "source_count": len(source_manifest),
            "source_checksums": source_manifest,
            "acquisition_failures": failures,
            "template_groups": labels.get("templates", []),
            "manual_annotation_policy": labels.get("label_policy"),
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path.name}")
    return value


def _validated_inputs(
    fresh_dir: Path, manifest: dict[str, Any], labels: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if manifest.get("format") != "fresh-product-pages-v1":
        raise ValueError("unsupported fresh-page manifest format")
    if labels.get("format") != "product-retrieval-manual-labels-v1":
        raise ValueError("unsupported fresh-page label format")
    if "not a blind holdout" not in str(labels.get("annotation_status", "")):
        raise ValueError("manual labels must state their annotation/blinding status")

    manifest_pages = manifest.get("pages")
    label_pages = labels.get("pages")
    if not isinstance(manifest_pages, list) or not isinstance(label_pages, list):
        raise ValueError("manifest and labels must contain page lists")
    manifest_by_id = {page.get("id"): page for page in manifest_pages}
    labels_by_id = {page.get("id"): page for page in label_pages}
    if len(manifest_by_id) != len(manifest_pages) or len(labels_by_id) != len(
        label_pages
    ):
        raise ValueError("duplicate page IDs in manifest or labels")

    failures = [
        {
            "id": page.get("id"),
            "requested_url": page.get("requested_url"),
            "status": page.get("status"),
            "error": page.get("error"),
        }
        for page in manifest_pages
        if page.get("status") != 200 or page.get("error")
    ]
    successful_ids = {
        page_id
        for page_id, page in manifest_by_id.items()
        if page.get("status") == 200 and not page.get("error")
    }
    if set(labels_by_id) != successful_ids:
        missing_labels = sorted(successful_ids - set(labels_by_id))
        labels_without_source = sorted(set(labels_by_id) - successful_ids)
        raise ValueError(
            "manual labels must cover exactly the successful captures "
            f"(unlabeled={missing_labels}, "
            f"labels_without_capture={labels_without_source})"
        )

    successful = [
        manifest_by_id[page_id]
        for page_id in manifest_by_id
        if page_id in successful_ids
    ]
    templates = {page.get("site_template") for page in successful}
    if len(successful) < 6 or len(templates) < 3:
        raise ValueError(
            "fresh corpus requires at least six pages across three templates"
        )

    for page in successful:
        page_id = page.get("id")
        body_path = _safe_source_path(fresh_dir, str(page.get("file", "")))
        body = body_path.read_bytes()
        expected_length = page.get("byte_len")
        expected_digest = page.get("sha256")
        if len(body) != expected_length:
            raise ValueError(f"saved HTML length mismatch for {page_id}")
        if not isinstance(expected_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_digest
        ):
            raise ValueError(f"invalid saved HTML SHA-256 in manifest for {page_id}")
        if hashlib.sha256(body).hexdigest() != expected_digest:
            raise ValueError(f"saved HTML SHA-256 mismatch for {page_id}")
        if len(body) > _MAX_SOURCE_BYTES:
            raise ValueError(f"saved HTML exceeds the source bound for {page_id}")
        if "text/html" not in str(page.get("content_type", "")).lower():
            raise ValueError(f"capture is not identified as HTML for {page_id}")

    return successful, labels_by_id, failures


def _safe_source_path(fresh_dir: Path, relative: str) -> Path:
    candidate = (fresh_dir / relative).resolve()
    root = fresh_dir.resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError(f"source path escapes fresh corpus directory: {relative}")
    if not candidate.is_file():
        raise ValueError(f"missing saved source HTML: {relative}")
    return candidate


def _normalize_html(payload: bytes) -> dict[str, Any]:
    if len(payload) > _MAX_SOURCE_BYTES:
        raise ValueError("source HTML exceeds the 1.5 MB normalization bound")
    parser = html5lib.HTMLParser(
        tree=html5lib.getTreeBuilder("etree"),
        strict=False,
        namespaceHTMLElements=True,
    )
    parsed_root = parser.parse(payload, scripting=True)
    nodes: list[dict[str, Any]] = [
        {"kind": "document", "id": 1, "parent": None, "children": []}
    ]
    by_id: dict[int, dict[str, Any]] = {1: nodes[0]}
    next_id = 2

    def add_text(value: str | None, parent_id: int) -> None:
        nonlocal next_id
        if value is None:
            return
        node_id = next_id
        next_id += 1
        node = {
            "kind": "text",
            "id": node_id,
            "parent": parent_id,
            "children": [],
            "value": value,
        }
        nodes.append(node)
        by_id[node_id] = node
        by_id[parent_id]["children"].append(node_id)

    def add_element(element: Any, parent_id: int) -> None:
        nonlocal next_id
        tag = getattr(element, "tag", None)
        if not isinstance(tag, str):
            return
        namespace, local_tag = _split_expanded_name(tag)
        node_id = next_id
        next_id += 1
        attributes = []
        for name, value in element.attrib.items():
            attribute_namespace, local_name = _split_expanded_name(str(name))
            attributes.append(
                {
                    "namespace_uri": attribute_namespace,
                    "name": local_name,
                    "value": str(value),
                }
            )
        attributes.sort(
            key=lambda attribute: (attribute["namespace_uri"], attribute["name"])
        )
        node = {
            "kind": "element",
            "id": node_id,
            "parent": parent_id,
            "children": [],
            "namespace_uri": namespace,
            "tag_name": local_tag,
            "attributes": attributes,
        }
        nodes.append(node)
        by_id[node_id] = node
        by_id[parent_id]["children"].append(node_id)
        add_text(element.text, node_id)
        for child in list(element):
            if isinstance(getattr(child, "tag", None), str):
                add_element(child, node_id)
            add_text(getattr(child, "tail", None), node_id)

    add_element(parsed_root, 1)
    if len(nodes) < 3:
        raise ValueError("HTML5 normalization produced no document elements")
    return {
        "document_epoch": 1,
        "nodes": nodes,
        "root": 1,
        "schema": "yosoi.rendered-dom.v1",
        "tree_model": "document_light_dom",
    }


def _split_expanded_name(name: str) -> tuple[str, str]:
    if name.startswith("{") and "}" in name:
        namespace, local_name = name[1:].split("}", 1)
        return namespace, local_name
    return "", name


def _build_case(
    page_id: str,
    manifest_entry: dict[str, Any],
    label: dict[str, Any],
    payload: bytes,
    document: dict[str, Any],
) -> dict[str, Any]:
    case_id = page_id
    family = str(manifest_entry["site_template"])
    candidates = build_candidates(document, case_id)
    index = _index_document(document)
    root_id, targets = _annotate_source_fields(document, index, label)

    expected: dict[str, list[str]] = {"root": []}
    canonical_expected: dict[str, list[str]] = {"root": []}
    expected_values: dict[str, str] = {}
    expected_present: dict[str, bool] = {"root": True}
    expected_status: dict[str, str] = {"root": "present_dom"}
    canonical_values: dict[str, Any] = {}
    root_candidates = [
        candidate["id"]
        for candidate in candidates
        if candidate["node_id"] == str(root_id) and candidate["projection"] == "text"
    ]
    if not root_candidates:
        raise ValueError(f"annotated product root has no candidate in {page_id}")
    expected["root"] = root_candidates
    canonical_expected["root"] = root_candidates

    field_labels = label["contract_fields"]
    for field_name in _FIELDS:
        field_label = field_labels[field_name]
        status = str(field_label.get("status", ""))
        target = targets.get(field_name)
        external_id = (
            field_name == "id"
            and label.get("identity", {}).get("scheme") == "product URL path ID"
        )
        expected_present[field_name] = status in {"present", "present_external_url"}
        expected_status[field_name] = _status_code(
            field_name, field_label, label.get("identity", {})
        )
        if status == "present" and target is None and not external_id:
            expected_status[field_name] = "present_unlocatable"
        value = ""
        if expected_present[field_name]:
            value = _field_value(field_name, field_label)
            if target is not None:
                value = _node_text(index, target[0])
                if not _value_matches_label(field_name, value, field_label):
                    raise ValueError(
                        f"manual {field_name} label does not match source node "
                        f"in {page_id}"
                    )
            expected_values[field_name] = value

        if target is None:
            expected[field_name] = []
            canonical_expected[field_name] = []
            continue

        target_id, projection = target
        aliases = _candidate_aliases(
            candidates,
            document,
            target_id,
            projection,
            value,
        )
        canonical = [
            candidate["id"]
            for candidate in candidates
            if candidate["node_id"] == str(target_id)
            and candidate["projection"] == projection
            and candidate["text"] == value
        ]
        if not aliases or not canonical:
            raise ValueError(
                f"source annotation for {field_name} has no candidate in {page_id}"
            )
        expected[field_name] = aliases
        canonical_expected[field_name] = canonical

    price_label = field_labels["price"]
    if price_label.get("status") == "present":
        canonical_values["price"] = {
            "amount": str(price_label["amount"]),
            "currency": str(price_label["currency"]),
        }
    identity = label["identity"]
    identity_scope = (
        "external_url" if identity.get("scheme") == "product URL path ID" else "dom"
    )
    canonical_values["identity"] = {
        "scheme": str(identity["scheme"]),
        "value": str(identity["value"]),
        "evidence_scope": identity_scope,
    }

    return {
        "id": case_id,
        "source_id": page_id,
        "split": "fresh_cross_site",
        "variant": "original",
        "family": family,
        "document": document,
        "candidates": candidates,
        "expected": expected,
        "canonical_expected": canonical_expected,
        "expected_values": expected_values,
        "expected_present": expected_present,
        "expected_status": expected_status,
        "canonical_values": canonical_values,
        "owning_root_id": str(root_id),
        "optional_fields": label.get("optional_fields", {}),
        "provenance": {
            "source_representation": "captured_http_response_html",
            "source_url": manifest_entry["requested_url"],
            "final_url": manifest_entry["final_url"],
            "retrieved_at_utc": manifest_entry["retrieved_at_utc"],
            "source_html_sha256": hashlib.sha256(payload).hexdigest(),
            "source_html_byte_len": len(payload),
            "normalized_document_sha256": _document_sha256(document),
            "normalizer": {
                "library": "html5lib",
                "version": html5lib.__version__,
                "tree_builder": "etree",
                "scripting": True,
                "namespace_html_elements": True,
                "javascript_executed": False,
            },
            "live_rendered_dom": False,
            "wire_document_epoch": 1,
            "wire_epoch_is_synthetic": True,
            "observed_browser_epoch": None,
            "annotation": "manual_source_grounded",
            "annotation_evidence": label.get("evidence_summary", {}),
        },
    }


def _annotate_source_fields(
    document: dict[str, Any], index: dict[str, Any], label: dict[str, Any]
) -> tuple[Any, dict[str, tuple[Any, str]]]:
    template = label["site_template"]
    nodes = index["nodes"]
    label_fields = label["contract_fields"]
    id_status = label_fields["id"].get("status")

    if template == "books_to_scrape":
        roots = [
            node_id
            for node_id, node in nodes.items()
            if node.get("kind") == "element"
            and _tag(node) == "article"
            and "product_page" in _classes(node)
        ]
    elif template == "webscraper_ecommerce_static":
        roots = [
            node_id
            for node_id, node in nodes.items()
            if node.get("kind") == "element"
            and _tag(node) == "div"
            and {"card", "thumbnail"}.issubset(_classes(node))
            and _contains_itemprop_name(node_id, document, index)
        ]
    elif template == "scrapeme_woocommerce":
        post_id = str(label["identity"].get("alternate_post_id", ""))
        roots = [
            node_id
            for node_id, node in nodes.items()
            if node.get("kind") == "element"
            and _tag(node) == "div"
            and _attributes(node).get("id") == f"product-{post_id}"
        ]
    else:
        raise ValueError(f"unsupported annotated template {template}")
    if len(roots) != 1:
        raise ValueError(
            f"expected one source-defined root for {label['id']}, found {len(roots)}"
        )
    root_id = roots[0]
    root_nodes = {root_id, *_descendants(document, root_id)}

    def find_one(predicate: Any, description: str) -> Any:
        matches = [
            node_id
            for node_id in root_nodes
            if nodes[node_id].get("kind") == "element" and predicate(nodes[node_id])
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one {description} for {label['id']}, found {len(matches)}"
            )
        return matches[0]

    if template == "books_to_scrape":
        name_id = find_one(lambda node: _tag(node) == "h1", "book heading")
        price_id = find_one(
            lambda node: (
                "price_color" in _classes(node)
                and _value_matches_label(
                    "price", _node_text(index, node["id"]), label_fields["price"]
                )
            ),
            "main book price",
        )
        stock_value = _field_value("stock", label_fields["stock"])
        stock_id = find_one(
            lambda node: (
                "availability" in _classes(node)
                and _node_text(index, node["id"]) == stock_value
            ),
            "book availability",
        )
        targets: dict[str, tuple[Any, str]] = {
            "name": (name_id, "text"),
            "price": (price_id, "text"),
            "stock": (stock_id, "text"),
        }
        if id_status == "present":
            identity_value = _field_value("id", label_fields["id"])
            identity_id = _find_book_upc_cell(root_id, document, index, identity_value)
            targets["id"] = (identity_id, "text")
        return root_id, targets

    if template == "webscraper_ecommerce_static":
        name_id = find_one(
            lambda node: (
                _tag(node) == "h4" and _attributes(node).get("itemprop") == "name"
            ),
            "itemprop product name",
        )
        price_id = find_one(
            lambda node: (
                _tag(node) == "span"
                and _attributes(node).get("itemprop") == "price"
                and _value_matches_label(
                    "price", _node_text(index, node["id"]), label_fields["price"]
                )
            ),
            "itemprop product price",
        )
        targets = {"name": (name_id, "text"), "price": (price_id, "text")}
        if label.get("identity", {}).get("scheme") != "product URL path ID":
            raise ValueError(
                "Web Scraper URL-only identity must not be treated as DOM identity"
            )
        return root_id, targets

    name_id = find_one(
        lambda node: _tag(node) == "h1" and "product_title" in _classes(node),
        "WooCommerce product heading",
    )
    price_id = find_one(
        lambda node: (
            _tag(node) == "p"
            and "price" in _classes(node)
            and _value_matches_label(
                "price", _node_text(index, node["id"]), label_fields["price"]
            )
        ),
        "WooCommerce product price",
    )
    targets = {
        "name": (name_id, "text"),
        "price": (price_id, "text"),
    }
    if id_status == "present":
        sku_value = _field_value("id", label_fields["id"])
        sku_id = find_one(
            lambda node: (
                _tag(node) == "span"
                and "sku" in _classes(node)
                and _node_text(index, node["id"]) == sku_value
            ),
            "SKU",
        )
        targets["id"] = (sku_id, "text")
    stock_status = label_fields["stock"].get("status")
    if stock_status == "present":
        stock_value = _field_value("stock", label_fields["stock"])
        stock_id = find_one(
            lambda node: (
                _tag(node) == "p"
                and "stock" in _classes(node)
                and _node_text(index, node["id"]) == stock_value
            ),
            "WooCommerce stock value",
        )
        targets["stock"] = (stock_id, "text")
    return root_id, targets


def _find_book_upc_cell(
    root_id: Any, document: dict[str, Any], index: dict[str, Any], expected_value: str
) -> Any:
    nodes = index["nodes"]
    for node_id in {root_id, *_descendants(document, root_id)}:
        node = nodes[node_id]
        if node.get("kind") != "element" or _tag(node) != "tr":
            continue
        children = [
            child_id
            for child_id in node.get("children", [])
            if nodes[child_id].get("kind") == "element"
        ]
        if len(children) >= 2 and _node_text(index, children[0]) == "UPC":
            if _node_text(index, children[1]) != expected_value:
                raise ValueError(
                    "labeled book UPC does not match Product Information row"
                )
            return children[1]
    raise ValueError("book Product Information table has no UPC row")


def _candidate_aliases(
    candidates: list[dict[str, Any]],
    document: dict[str, Any],
    target_id: Any,
    projection: str,
    expected_value: str,
) -> list[str]:
    equivalent_ids = {target_id}
    if projection == "text":
        equivalent_ids.update(_descendants(document, target_id))
    candidate_nodes = {str(node_id) for node_id in equivalent_ids}
    return [
        candidate["id"]
        for candidate in candidates
        if candidate["node_id"] in candidate_nodes
        and candidate["projection"] == projection
        and candidate["text"] == expected_value
    ]


def _field_value(field_name: str, label: dict[str, Any]) -> str:
    if field_name == "price":
        if "source_text" in label:
            return _normalize(str(label["source_text"]))
        return _normalize(str(label["display"]))
    if field_name == "id":
        return _normalize(str(label.get("value", "")))
    return _normalize(str(label.get("value", "")))


def _value_matches_label(field_name: str, value: str, label: dict[str, Any]) -> bool:
    observed = _normalize(value)
    if field_name != "price":
        return observed == _field_value(field_name, label)
    amount = str(label.get("amount", ""))
    currency = str(label.get("currency", ""))
    symbol = {"GBP": "£", "USD": "$"}.get(currency)
    return bool(amount and symbol and amount in observed and symbol in observed)


def _status_code(
    field_name: str, label: dict[str, Any], identity: dict[str, Any]
) -> str:
    status = str(label.get("status", ""))
    if status == "absent":
        return "absent"
    if status in {"present_external_url", "present_url"}:
        return "present_external_url"
    if status == "present":
        scope = label.get("evidence_scope")
        if field_name == "id" and identity.get("scheme") == "product URL path ID":
            scope = "url"
        return "present_external_url" if scope == "url" else "present_dom"
    if status in {"ambiguous", "unavailable", "missing_in_source"}:
        return status
    raise ValueError(f"unsupported field status: {status}")


def _contains_itemprop_name(
    root_id: Any, document: dict[str, Any], index: dict[str, Any]
) -> bool:
    nodes = index["nodes"]
    return any(
        nodes[node_id].get("kind") == "element"
        and _tag(nodes[node_id]) == "h4"
        and _attributes(nodes[node_id]).get("itemprop") == "name"
        for node_id in {root_id, *_descendants(document, root_id)}
    )


def _node_text(index: dict[str, Any], node_id: Any) -> str:
    return _normalize(index["text"].get(node_id, ""))


def _tag(node: dict[str, Any]) -> str:
    return str(node.get("tag_name", "")).lower()


def _attributes(node: dict[str, Any]) -> dict[str, str]:
    return {
        str(attribute.get("name", "")): str(attribute.get("value", ""))
        for attribute in node.get("attributes", [])
        if attribute.get("name")
    }


def _classes(node: dict[str, Any]) -> set[str]:
    return set(_attributes(node).get("class", "").split())


def _document_sha256(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _default_fresh_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / ".generated" / "product-retrieval-fresh"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-dir", type=Path, default=_default_fresh_dir())
    args = parser.parse_args()
    corpus = build_fresh_corpus(args.fresh_dir)
    output_path = args.fresh_dir / "corpus-v1.json"
    output_path.write_text(
        json.dumps(corpus, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cases": len(corpus["cases"]),
                "candidates": sum(len(case["candidates"]) for case in corpus["cases"]),
                "output": str(output_path),
            }
        )
    )


if __name__ == "__main__":
    main()
