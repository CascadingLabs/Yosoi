"""Bounded structured-product extraction experiment over retained source HTML.

This is research code, not a Yosoi SDK feature. It reads source HTML only. It
does not execute JavaScript, use selectors, infer values from visible prose, or
claim that embedded metadata is visible, fresh, or true.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import html.parser
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[3]
FRESH = ROOT / ".generated" / "product-retrieval-fresh"
OUTPUT = ROOT / ".generated" / "product-retrieval-structured-v1"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_SCRIPT_BYTES = 256 * 1024
MAX_HTML_NODES = 5_000
MAX_JSON_NODES = 5_000
MAX_DEPTH = 64
VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
PRODUCT_FIELDS = ("name", "sku", "productID", "color", "material")
OFFER_FIELDS = ("price", "priceCurrency")
AVAILABILITY_ENUMS = {
    "InStock": "in_stock",
    "LimitedAvailability": "limited_availability",
    "OutOfStock": "out_of_stock",
    "PreOrder": "pre_order",
    "BackOrder": "back_order",
    "SoldOut": "sold_out",
    "Discontinued": "discontinued",
    "InStoreOnly": "in_store_only",
    "OnlineOnly": "online_only",
    "MadeToOrder": "made_to_order",
    "PreSale": "pre_sale",
    "Reserved": "reserved",
}


def _schema_type(uri: str) -> str | None:
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc.lower() != "schema.org"
        or parsed.query
        or parsed.fragment
    ):
        return None
    for name in ("Product", "Offer"):
        if parsed.path in {f"/{name}", f"/{name}/"}:
            return name
    return None


def _pointer(parent: str, token: str | int) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


class _HtmlTokens(html.parser.HTMLParser):
    """HTMLParser-backed simple profile with HTML5 ownership boundaries.

    This profile follows itemscope/itemprop descendant ownership for properly
    nested HTML. It does not implement HTML5 error recovery, itemref, templates,
    shadow DOM, SVG/MathML integration, or browser DOM construction. Such cases
    are reported as partial where detected.
    """

    def __init__(self, source: str, max_nodes: int = MAX_HTML_NODES) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.max_nodes = max_nodes
        self.nodes: list[dict[str, Any]] = []
        self.stack: list[int] = []
        self.scripts: list[dict[str, Any]] = []
        self.active_script: dict[str, Any] | None = None
        self.issues: list[str] = []
        self.depth_limited = False
        self.node_limited = False
        self.matched_offsets: array.array | None = None
        if not source.isascii():
            offsets = array.array("I", [0])
            total = 0
            for char in source:
                total += len(char.encode("utf-8"))
                offsets.append(total)
            self.matched_offsets = offsets
        self.line_starts = [0]
        for index, char in enumerate(source):
            if char == "\n":
                self.line_starts.append(index + 1)

    def _char_offset(self) -> int:
        line, column = self.getpos()
        index = min(line - 1, len(self.line_starts) - 1)
        return self.line_starts[index] + column

    def _byte_offset(self, char_offset: int) -> int:
        if self.matched_offsets is None:
            return char_offset
        return self.matched_offsets[min(char_offset, len(self.matched_offsets) - 1)]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self.get_starttag_text() or "")
        self._end(tag)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], token: str) -> None:
        if len(self.nodes) >= self.max_nodes:
            self.node_limited = True
            return
        if len(self.stack) >= MAX_DEPTH:
            self.depth_limited = True
            return
        start_char = self._char_offset()
        node_id = len(self.nodes) + 1
        node = {
            "node_id": node_id,
            "tag": tag.lower(),
            "parent": self.stack[-1] if self.stack else None,
            "children": [],
            "content": [],
            "attrs": {key.lower(): value or "" for key, value in attrs},
            "start_byte": self._byte_offset(start_char),
            "start_tag_end_byte": self._byte_offset(start_char + len(token)),
            "end_tag_start_byte": None,
            "end_tag_end_byte": None,
        }
        self.nodes.append(node)
        if self.stack:
            self.nodes[self.stack[-1] - 1]["children"].append(node_id)
            self.nodes[self.stack[-1] - 1]["content"].append(("node", node_id))
        if tag.lower() == "script":
            script = {
                "ordinal": len(self.scripts),
                "type": node["attrs"].get("type", "").strip().lower(),
                "node_id": node_id,
                "start_byte": node["start_byte"],
                "body": [],
                "body_bytes": 0,
                "end_byte": None,
                "overflow": False,
            }
            self.scripts.append(script)
            self.active_script = script
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node_id)

    def handle_endtag(self, tag: str) -> None:
        self._end(tag)

    def _end(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        start = self._char_offset()
        if tag == "script" and self.active_script is not None:
            close_end = self.source.find(">", start)
            self.active_script["end_byte"] = self._byte_offset(
                close_end + 1 if close_end >= 0 else start
            )
            self.active_script = None
        found = next(
            (
                offset
                for offset in range(len(self.stack) - 1, -1, -1)
                if self.nodes[self.stack[offset] - 1]["tag"] == tag
            ),
            None,
        )
        if found is None:
            self.issues.append(f"orphan_end_tag:{tag}")
            return
        if found != len(self.stack) - 1:
            self.issues.append(f"implicit_close_before:{tag}")
        node_id = self.stack[found]
        close_end = self.source.find(">", start)
        node = self.nodes[node_id - 1]
        node["end_tag_start_byte"] = self._byte_offset(start)
        node["end_tag_end_byte"] = self._byte_offset(
            close_end + 1 if close_end >= 0 else start
        )
        del self.stack[found:]

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.nodes[self.stack[-1] - 1]["content"].append(("text", data))
        if self.active_script is not None:
            byte_count = len(data.encode("utf-8"))
            self.active_script["body_bytes"] += byte_count
            if self.active_script["body_bytes"] <= MAX_SCRIPT_BYTES:
                self.active_script["body"].append(data)
            else:
                self.active_script["overflow"] = True


def _source_span(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node["node_id"],
        "start_byte": node["start_byte"],
        "start_tag_end_byte": node["start_tag_end_byte"],
    }


def _descendant_text(nodes: list[dict[str, Any]], node_id: int) -> str:
    parts: list[str] = []
    pending: list[tuple[str, Any]] = [("node", node_id)]
    while pending:
        kind, value = pending.pop()
        if kind == "text":
            parts.append(value)
            continue
        current = nodes[value - 1]
        pending.extend(reversed(current["content"]))
    return "".join(parts)


def _property_names(node: dict[str, Any]) -> list[str]:
    return node["attrs"].get("itemprop", "").split()


def _microdata_value(
    nodes: list[dict[str, Any]], node: dict[str, Any]
) -> tuple[Any, str]:
    if "itemscope" in node["attrs"]:
        return {"node_id": node["node_id"]}, "nested_item_reference"
    tag = node["tag"]
    attr = {
        "meta": "content",
        "audio": "src",
        "embed": "src",
        "iframe": "src",
        "img": "src",
        "source": "src",
        "track": "src",
        "video": "src",
        "a": "href",
        "area": "href",
        "link": "href",
        "object": "data",
        "data": "value",
        "meter": "value",
        "time": "datetime",
    }.get(tag)
    if attr is not None:
        return node["attrs"].get(attr, ""), f"html_{attr}"
    return _descendant_text(nodes, node["node_id"]), "text_content"


def _availability(
    value: Any, value_kind: str, source: dict[str, Any]
) -> dict[str, Any]:
    raw = str(value)
    enum_name = None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        parsed = urlsplit("")
        value_kind = "malformed_uri_or_text"
    if (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() == "schema.org"
        and not parsed.query
        and not parsed.fragment
    ):
        enum_name = next(
            (
                enum
                for name, enum in AVAILABILITY_ENUMS.items()
                if parsed.path in {f"/{name}", f"/{name}/"}
            ),
            None,
        )
    if enum_name:
        effective_kind = "schema_org_availability_uri"
    elif parsed.scheme in {"http", "https"}:
        effective_kind = "unrecognized_uri"
    elif value_kind in {"json_literal", "json_number_token"}:
        effective_kind = "text"
    else:
        effective_kind = value_kind
    return {
        "raw_value": raw,
        "enum": enum_name or "unknown",
        "value_kind": effective_kind,
        "source": source,
    }


class _JsonNumber(str):
    """A JSON numeric token retained without float normalization."""


def _literal_values(
    value: Any, pointer: str, source: dict[str, Any]
) -> list[dict[str, Any]]:
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            result.extend(_literal_values(item, _pointer(pointer, index), source))
        return result
    if isinstance(value, _JsonNumber):
        return [
            {
                "value": str(value),
                "value_kind": "json_number_token",
                "source": {**source, "json_pointer": pointer},
            }
        ]
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return [
            {
                "value": str(value),
                "value_kind": "json_literal",
                "source": {**source, "json_pointer": pointer},
            }
        ]
    if isinstance(value, dict) and "@value" in value:
        return _literal_values(value["@value"], _pointer(pointer, "@value"), source)
    return []


def _context_for(value: Any, inherited: dict[str, Any]) -> dict[str, Any]:
    context = {
        "schema_vocab": inherited.get("schema_vocab", False),
        "aliases": dict(inherited.get("aliases", {})),
    }
    values = value if isinstance(value, list) else [value]
    for entry in values:
        if isinstance(entry, str):
            if entry.rstrip("/") in {"https://schema.org", "http://schema.org"}:
                context["schema_vocab"] = True
        elif isinstance(entry, dict):
            if "@base" in entry:
                context["unsupported"] = True
            vocab = entry.get("@vocab")
            if isinstance(vocab, str) and vocab.rstrip("/") in {
                "https://schema.org",
                "http://schema.org",
            }:
                context["schema_vocab"] = True
            for name, target in entry.items():
                if name.startswith("@") or not isinstance(target, str):
                    continue
                if _schema_type(target) is not None:
                    context["aliases"][name] = _schema_type(target)
                    if not context["schema_vocab"]:
                        context["unsupported"] = True
                else:
                    context["unsupported"] = True
        else:
            context["unsupported"] = True
    if isinstance(value, str) and value.rstrip("/") not in {
        "https://schema.org",
        "http://schema.org",
    }:
        context["unsupported"] = True
    if isinstance(value, dict) and "@vocab" in value and not context["schema_vocab"]:
        context["unsupported"] = True
    return context


def _json_types(node: dict[str, Any], context: dict[str, Any]) -> set[str]:
    raw = node.get("@type", [])
    values = raw if isinstance(raw, list) else [raw]
    result: set[str] = set()
    for value in values:
        if type(value) is not str:
            continue
        normalized = _schema_type(value)
        if normalized is not None:
            result.add(normalized)
        elif value in {"Product", "Offer"} and context.get("schema_vocab"):
            result.add(value)
        elif value in context.get("aliases", {}):
            result.add(context["aliases"][value])
    return result


def _json_property_keys(entry: dict[str, Any], field: str) -> list[str]:
    """Return only Schema.org-expanded or inline-vocabulary property keys."""
    obj = entry["object"]
    context = entry["context"]
    keys = []
    if context.get("schema_vocab") and field in obj:
        keys.append(field)
    for prefix in ("https://schema.org/", "http://schema.org/"):
        key = prefix + field
        if key in obj:
            keys.append(key)
    return keys


def _parse_jsonld(
    script: dict[str, Any], base_url: str, node_budget: int
) -> tuple[list[dict[str, Any]], list[str], int]:
    if script["overflow"] or script["body_bytes"] > MAX_SCRIPT_BYTES:
        return [], ["jsonld_script_over_256_kib"], 0
    body = "".join(script["body"])
    try:
        document = json.loads(
            body,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
            parse_int=_JsonNumber,
            parse_float=_JsonNumber,
        )
    except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError) as exc:
        return (
            [],
            [f"malformed_jsonld_script_{script['ordinal']}:{type(exc).__name__}"],
            0,
        )

    nodes: list[dict[str, Any]] = []
    issues: list[str] = []
    pending: list[tuple[Any, str, dict[str, Any], int]] = [(document, "", {}, 0)]
    while pending:
        value, pointer, context, depth = pending.pop()
        if depth > MAX_DEPTH:
            issues.append("jsonld_depth_over_64")
            continue
        if isinstance(value, list):
            for index in range(len(value) - 1, -1, -1):
                pending.append(
                    (value[index], _pointer(pointer, index), context, depth + 1)
                )
            continue
        if not isinstance(value, dict):
            continue
        if len(nodes) >= node_budget:
            issues.append("jsonld_graph_over_5000_nodes")
            break
        current_context = (
            _context_for(value.get("@context"), context)
            if "@context" in value
            else context
        )
        node = {
            "object": value,
            "pointer": pointer,
            "context": current_context,
            "id": value.get("@id") if type(value.get("@id")) is str else None,
            "resolved_id": _resolve_id(value["@id"], base_url)
            if type(value.get("@id")) is str
            else None,
        }
        nodes.append(node)
        if current_context.get("unsupported"):
            issues.append("unsupported_or_remote_jsonld_context_not_fetched")
        raw_types = value.get("@type", [])
        raw_types = raw_types if isinstance(raw_types, list) else [raw_types]
        if not current_context.get("schema_vocab"):
            if any(
                type(item) is str
                and item in {"Product", "Offer"}
                and item not in current_context.get("aliases", {})
                for item in raw_types
            ):
                issues.append("compact_product_or_offer_type_without_schema_context")
            supported_properties = set(
                PRODUCT_FIELDS + OFFER_FIELDS + ("offers", "availability")
            )
            if any(key in supported_properties for key in value):
                if any(
                    _schema_type(item) in {"Product", "Offer"}
                    for item in raw_types
                    if type(item) is str
                ):
                    issues.append("compact_schema_properties_without_schema_context")
        children = [(key, child) for key, child in value.items() if key != "@context"]
        for key, child in reversed(children):
            pending.append((child, _pointer(pointer, key), current_context, depth + 1))
    return nodes, sorted(set(issues)), len(nodes)


def _json_candidate_fields(
    node_entries: list[dict[str, Any]],
    fields: tuple[str, ...],
    source_base: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    result = {field: [] for field in fields}
    for entry in node_entries:
        obj = entry["object"]
        for field in fields:
            for key in _json_property_keys(entry, field):
                source = {**source_base, "node_pointer": entry["pointer"]}
                result[field].extend(
                    _literal_values(obj[key], _pointer(entry["pointer"], key), source)
                )
    return result


def _json_id_key(value: str, base_url: str) -> str:
    return _resolve_id(value, base_url) or value


def _resolve_id(value: str, base_url: str) -> str | None:
    try:
        return urljoin(base_url, value)
    except ValueError:
        return None


def _jsonld_candidates(
    nodes: list[dict[str, Any]], source: dict[str, Any], base_url: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    id_index: dict[str, list[dict[str, Any]]] = {}
    product_by_pointer: dict[str, dict[str, Any]] = {}
    offer_by_pointer: dict[str, dict[str, Any]] = {}
    entry_by_pointer = {entry["pointer"]: entry for entry in nodes}
    for entry in nodes:
        if entry["resolved_id"]:
            id_index.setdefault(entry["resolved_id"], []).append(entry)
        types = _json_types(entry["object"], entry["context"])
        if "Product" in types:
            candidate = {
                "candidate_id": (
                    f"{source['page_id']}:jsonld:product:{entry['pointer']}"
                ),
                "syntax": "jsonld",
                "schema_id": entry["id"],
                "source": {**source, "node_pointer": entry["pointer"]},
                "fields": _json_candidate_fields([entry], PRODUCT_FIELDS, source),
                "offer_refs": [],
                "offer_links": [],
                "unresolved_offer_references": [],
            }
            products.append(candidate)
            product_by_pointer[entry["pointer"]] = candidate
        if "Offer" in types:
            candidate = {
                "candidate_id": f"{source['page_id']}:jsonld:offer:{entry['pointer']}",
                "syntax": "jsonld",
                "schema_id": entry["id"],
                "source": {**source, "node_pointer": entry["pointer"]},
                "fields": _json_candidate_fields([entry], OFFER_FIELDS, source),
                "availability": [],
            }
            for key in _json_property_keys(entry, "availability"):
                raw_availability = entry["object"][key]
                for item in _literal_values(
                    raw_availability, _pointer(entry["pointer"], key), source
                ):
                    candidate["availability"].append(
                        _availability(item["value"], item["value_kind"], item["source"])
                    )
            offers.append(candidate)
            offer_by_pointer[entry["pointer"]] = candidate

    def find_offer_refs(
        value: Any, pointer: str, visited: frozenset[str], depth: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        if depth > MAX_DEPTH:
            return [], [], ["reference_depth_over_64"]
        if isinstance(value, list):
            refs: list[dict[str, Any]] = []
            unresolved: list[dict[str, Any]] = []
            issues: list[str] = []
            for index, item in enumerate(value):
                found, missing, notes = find_offer_refs(
                    item, _pointer(pointer, index), visited, depth + 1
                )
                refs.extend(found)
                unresolved.extend(missing)
                issues.extend(notes)
            return refs, unresolved, issues
        if not isinstance(value, dict):
            return [], [], []
        direct_entry = entry_by_pointer.get(pointer)
        direct = [direct_entry] if direct_entry is not None else []
        if direct and any(
            "Offer" in _json_types(item["object"], item["context"]) for item in direct
        ):
            return (
                [
                    offer_by_pointer[item["pointer"]]
                    for item in direct
                    if item["pointer"] in offer_by_pointer
                ],
                [],
                [],
            )
        raw_id = value.get("@id")
        if type(raw_id) is str:
            resolved = _json_id_key(raw_id, base_url)
            if resolved in visited:
                return (
                    [],
                    [
                        {
                            "raw_id": raw_id,
                            "json_pointer": pointer,
                            "resolution": "cycle",
                        }
                    ],
                    [],
                )
            targets = id_index.get(resolved, [])
            if not targets:
                return (
                    [],
                    [
                        {
                            "raw_id": raw_id,
                            "json_pointer": pointer,
                            "resolution": "unresolved",
                        }
                    ],
                    [],
                )
            refs: list[dict[str, Any]] = []
            missing: list[dict[str, Any]] = []
            issues: list[str] = []
            for target in targets:
                target_types = _json_types(target["object"], target["context"])
                if "Offer" in target_types and target["pointer"] in offer_by_pointer:
                    refs.append(offer_by_pointer[target["pointer"]])
                else:
                    for key in _json_property_keys(target, "offers"):
                        nested = target["object"][key]
                        found, absent, notes = find_offer_refs(
                            nested,
                            _pointer(target["pointer"], key),
                            visited | {resolved},
                            depth + 1,
                        )
                        refs.extend(found)
                        missing.extend(absent)
                        issues.extend(notes)
            if not refs and not missing:
                missing.append(
                    {
                        "raw_id": raw_id,
                        "json_pointer": pointer,
                        "resolution": "target_not_offer",
                    }
                )
            return refs, missing, issues
        if direct_entry is not None:
            refs: list[dict[str, Any]] = []
            missing: list[dict[str, Any]] = []
            issues: list[str] = []
            for key in _json_property_keys(direct_entry, "offers"):
                found, absent, notes = find_offer_refs(
                    value[key], _pointer(pointer, key), visited, depth + 1
                )
                refs.extend(found)
                missing.extend(absent)
                issues.extend(notes)
            return refs, missing, issues
        return [], [], []

    for entry in nodes:
        product = product_by_pointer.get(entry["pointer"])
        offer_keys = _json_property_keys(entry, "offers")
        if product is None or not offer_keys:
            continue
        refs: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        issues: list[str] = []
        links: list[dict[str, Any]] = []
        for key in offer_keys:
            found, absent, notes = find_offer_refs(
                entry["object"][key], _pointer(entry["pointer"], key), frozenset(), 0
            )
            refs.extend(found)
            links.extend(
                {
                    "candidate_id": ref["candidate_id"],
                    "offers_property_pointer": _pointer(entry["pointer"], key),
                    "target_source": ref["source"],
                }
                for ref in found
            )
            missing.extend(absent)
            issues.extend(notes)
        product["offer_refs"] = list(dict.fromkeys(ref["candidate_id"] for ref in refs))
        product["offer_links"] = links
        product["unresolved_offer_references"] = missing
        if issues:
            product["resolution_notes"] = issues
    return products, offers


def _microdata_candidates(
    nodes: list[dict[str, Any]], source: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    products: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    issues: list[str] = []
    candidate_by_node: dict[int, list[dict[str, Any]]] = {}
    by_id = {node["node_id"]: node for node in nodes}
    blocked: set[int] = set()
    blocked_reason: dict[int, str] = {}
    for node in nodes:
        parent = node["parent"]
        reason = blocked_reason.get(parent) if parent is not None else None
        if reason is None and node["tag"] == "template":
            reason = "microdata_template_content_not_processed"
        elif reason is None and node["tag"] in {"svg", "math"}:
            reason = "microdata_foreign_content_not_processed"
        if reason is not None:
            blocked.add(node["node_id"])
            blocked_reason[node["node_id"]] = reason
            if {"itemscope", "itemtype", "itemprop", "itemref"}.intersection(
                node["attrs"]
            ):
                issues.append(reason)
    for node in nodes:
        if node["node_id"] in blocked:
            continue
        types = {
            kind
            for token in node["attrs"].get("itemtype", "").split()
            if (kind := _schema_type(token)) is not None
        }
        if types and "itemscope" not in node["attrs"]:
            issues.append("microdata_itemtype_without_itemscope")
            continue
        kinds = [kind for kind in ("Product", "Offer") if kind in types]
        if not kinds:
            continue
        if "itemref" in node["attrs"]:
            issues.append("microdata_itemref_not_supported")
        for kind in kinds:
            fields = PRODUCT_FIELDS if kind == "Product" else OFFER_FIELDS
            candidate = {
                "candidate_id": (
                    f"{source['page_id']}:microdata:{kind.lower()}:{node['node_id']}"
                ),
                "syntax": "microdata",
                "schema_id": None,
                "source": {
                    **source,
                    **_source_span(node),
                    "itemtype": node["attrs"].get("itemtype", ""),
                },
                "fields": {field: [] for field in fields},
            }
            if kind == "Product":
                candidate["offer_refs"] = []
                candidate["offer_links"] = []
                candidate["unresolved_offer_references"] = []
                products.append(candidate)
            else:
                candidate["availability"] = []
                offers.append(candidate)
            candidate_by_node.setdefault(node["node_id"], []).append(candidate)

    for node_id, candidates in candidate_by_node.items():
        for candidate in candidates:
            kind_fields = set(candidate["fields"])
            pending = list(reversed(by_id[node_id]["children"]))
            while pending:
                child = by_id[pending.pop()]
                if child["node_id"] in blocked:
                    continue
                property_names = _property_names(child)
                if "itemscope" in child["attrs"]:
                    if property_names:
                        for name in property_names:
                            if name in kind_fields:
                                candidate["fields"][name].append(
                                    {
                                        "value": {"node_id": child["node_id"]},
                                        "value_kind": "nested_item_reference",
                                        "source": {**source, **_source_span(child)},
                                    }
                                )
                            if name == "offers" and candidate in products:
                                target = next(
                                    (
                                        item
                                        for item in candidate_by_node.get(
                                            child["node_id"], []
                                        )
                                        if item in offers
                                    ),
                                    None,
                                )
                                if target is not None:
                                    candidate["offer_refs"].append(
                                        target["candidate_id"]
                                    )
                                    candidate["offer_links"].append(
                                        {
                                            "candidate_id": target["candidate_id"],
                                            "property_node_source": {
                                                **source,
                                                **_source_span(child),
                                            },
                                        }
                                    )
                    continue
                for name in property_names:
                    if name not in kind_fields and not (
                        name == "availability" and candidate in offers
                    ):
                        continue
                    value, value_kind = _microdata_value(nodes, child)
                    field_source = {**source, **_source_span(child)}
                    if name == "availability":
                        candidate["availability"].append(
                            _availability(value, value_kind, field_source)
                        )
                    else:
                        candidate["fields"][name].append(
                            {
                                "value": value,
                                "value_kind": value_kind,
                                "source": field_source,
                            }
                        )
                pending.extend(reversed(child["children"]))
    for product in products:
        product["offer_refs"] = list(dict.fromkeys(product["offer_refs"]))
    return products, offers, sorted(set(issues))


def extract_page(
    payload: bytes, page_id: str, final_url: str, expected_sha256: str | None = None
) -> dict[str, Any]:
    """Extract Product and Offer metadata from one retained HTML byte string."""
    digest = hashlib.sha256(payload).hexdigest()
    source_base = {
        "page_id": page_id,
        "final_url": final_url,
        "source_html_sha256": digest,
        "evidence_scope": "captured_source_html; rendered_visibility_unverified",
    }
    if len(payload) > MAX_INPUT_BYTES:
        return {
            "page_id": page_id,
            "status": "failed",
            "source": source_base,
            "candidateProducts": [],
            "candidateOffers": [],
            "issues": ["source_html_over_2_mib"],
        }
    if expected_sha256 is not None and digest != expected_sha256:
        return {
            "page_id": page_id,
            "status": "failed",
            "source": source_base,
            "candidateProducts": [],
            "candidateOffers": [],
            "issues": ["source_sha256_mismatch"],
        }
    try:
        text = payload.decode("utf-8", errors="strict")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = payload.decode("latin-1")
        encoding = "latin-1_fallback"
    parser = _HtmlTokens(text)
    chunk_size = 8192
    consumed = 0
    while consumed < len(text) and not parser.node_limited and not parser.depth_limited:
        chunk = text[consumed : consumed + chunk_size]
        parser.feed(chunk)
        consumed += len(chunk)
    if consumed == len(text) and not parser.node_limited and not parser.depth_limited:
        parser.close()
    nodes = parser.nodes
    issues = list(parser.issues)
    if parser.node_limited:
        issues.append("html_over_5000_nodes")
    if parser.depth_limited:
        issues.append("html_depth_over_64")
    if parser.stack and not parser.node_limited and not parser.depth_limited:
        issues.append("unclosed_html_elements")
    if encoding != "utf-8":
        issues.append("source_not_valid_utf8_offsets_use_latin1_decode")
    if any("itemref" in node["attrs"] for node in nodes):
        issues.append("microdata_itemref_not_supported")

    products, offers, micro_issues = _microdata_candidates(nodes, source_base)
    issues.extend(micro_issues)
    graph_nodes_used = 0
    jsonld_base_url = final_url
    for node in nodes:
        if node["tag"] == "base" and node["attrs"].get("href"):
            jsonld_base_url = _resolve_id(node["attrs"]["href"], final_url) or final_url
            break
    for script in parser.scripts:
        if script["type"].split(";", 1)[0].strip() != "application/ld+json":
            continue
        script_source = {
            **source_base,
            "script_ordinal": script["ordinal"],
            "script_node_id": script["node_id"],
            "script_start_byte": script["start_byte"],
            "script_end_byte": script["end_byte"],
            "jsonld_base_url": jsonld_base_url,
        }
        parsed, script_issues, used = _parse_jsonld(
            script, jsonld_base_url, max(0, MAX_JSON_NODES - graph_nodes_used)
        )
        graph_nodes_used += used
        issues.extend(script_issues)
        if parsed:
            json_products, json_offers = _jsonld_candidates(
                parsed, script_source, jsonld_base_url
            )
            products.extend(json_products)
            offers.extend(json_offers)
    for offer in offers:
        offer["monetary_evidence"] = _monetary_evidence(offer)
    if any(product["unresolved_offer_references"] for product in products):
        issues.append("jsonld_offer_reference_unresolved_or_cyclic")
    status = "partial" if issues else "complete"
    return {
        "page_id": page_id,
        "status": status,
        "source": {
            **source_base,
            "source_byte_len": len(payload),
            "decoded_as": encoding,
            "jsonld_base_url": jsonld_base_url,
        },
        "source_representation": "captured_http_response_html",
        "live_rendered_dom": False,
        "javascript_executed": False,
        "html_element_node_count": len(nodes),
        "jsonld_node_count": graph_nodes_used,
        "candidateProducts": products,
        "candidateOffers": offers,
        "issues": sorted(set(issues)),
    }


def _monetary_evidence(offer: dict[str, Any]) -> dict[str, Any]:
    amounts = [
        item
        for item in offer.get("fields", {}).get("price", [])
        if str(item.get("value", "")).strip()
    ]
    currencies = [
        item
        for item in offer.get("fields", {}).get("priceCurrency", [])
        if str(item.get("value", "")).strip()
    ]
    if len(amounts) == 1 and len(currencies) == 1:
        return {
            "status": "one_price_value_and_explicit_currency",
            "amount_raw": amounts[0].get("value"),
            "currency_raw": currencies[0].get("value"),
        }
    if amounts and not currencies:
        return {
            "status": "partial_amount_without_explicit_currency",
            "amounts_raw": [item.get("value") for item in amounts],
        }
    if currencies and not amounts:
        return {
            "status": "currency_without_amount",
            "currencies_raw": [item.get("value") for item in currencies],
        }
    if amounts or currencies:
        return {
            "status": "ambiguous_multiple_amounts_or_currencies",
            "amounts_raw": [item.get("value") for item in amounts],
            "currencies_raw": [item.get("value") for item in currencies],
        }
    return {"status": "no_price_evidence"}


def extract_manifest(
    fresh_dir: Path = FRESH, output_dir: Path = OUTPUT
) -> dict[str, Any]:
    """Extract all successful manifest sources and persist blind results."""
    manifest_path = fresh_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "fresh-product-pages-v1":
        raise ValueError("unsupported fresh-source manifest")
    pages: list[dict[str, Any]] = []
    started = time.process_time()
    for item in manifest.get("pages", []):
        if item.get("status") != 200 or item.get("error"):
            continue
        candidate = (fresh_dir / str(item.get("file", ""))).resolve()
        root = fresh_dir.resolve()
        if (
            candidate == root
            or root not in candidate.parents
            or not candidate.is_file()
        ):
            raise ValueError(f"unsafe or missing source path for {item.get('id')}")
        if candidate.stat().st_size > MAX_INPUT_BYTES:
            pages.append(
                {
                    "page_id": item["id"],
                    "status": "failed",
                    "source": {
                        "page_id": item["id"],
                        "source_html_sha256": item.get("sha256"),
                        "source_byte_len": candidate.stat().st_size,
                    },
                    "candidateProducts": [],
                    "candidateOffers": [],
                    "issues": ["source_html_over_2_mib"],
                }
            )
            continue
        payload = candidate.read_bytes()
        if len(payload) != item.get("byte_len"):
            raise ValueError(f"saved source byte length mismatch for {item.get('id')}")
        pages.append(
            extract_page(payload, item["id"], item["final_url"], item.get("sha256"))
        )
    cpu_seconds = time.process_time() - started
    result = {
        "format": "product-retrieval-structured-v1",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blind_extraction": False,
        "extractor_inputs_exclude_labels": True,
        "operator_prior_label_inspection": True,
        "source_manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "limits": {
            "source_html_bytes": MAX_INPUT_BYTES,
            "jsonld_script_bytes": MAX_SCRIPT_BYTES,
            "html_element_nodes_per_page": MAX_HTML_NODES,
            "jsonld_nodes_per_page": MAX_JSON_NODES,
            "nesting_depth": MAX_DEPTH,
        },
        "parser_profile": (
            "Python stdlib HTMLParser token tree; JSON-LD strict "
            "JSON subset; no JS, remote context fetch, CSS/XPath "
            "selectors, or HTML5 error recovery"
        ),
        "extractor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "standards": [
            {
                "name": "WHATWG HTML Microdata",
                "url": "https://html.spec.whatwg.org/multipage/microdata.html",
                "version": "living standard accessed 2026-10-31",
            },
            {
                "name": "Schema.org",
                "url": "https://schema.org/version/30.1/",
                "version": "30.1 published 2026-09-16",
            },
            {
                "name": "Schema.org Product",
                "url": "https://schema.org/Product",
                "version": "30.1",
            },
            {
                "name": "Schema.org Offer",
                "url": "https://schema.org/Offer",
                "version": "30.1",
            },
            {
                "name": "Schema.org price",
                "url": "https://schema.org/price",
                "version": "30.1",
            },
        ],
        "cpu_seconds": cpu_seconds,
        "source_count": len(pages),
        "pages": pages,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "extraction.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _field_values(
    candidates: list[dict[str, Any]], field: str
) -> list[tuple[dict[str, Any], str]]:
    result = []
    for candidate in candidates:
        for item in candidate.get("fields", {}).get(field, []):
            if isinstance(item.get("value"), (str, int, float)):
                result.append((candidate, _norm(item["value"])))
    return result


def evaluate_persisted(
    output_dir: Path = OUTPUT,
    corpus_path: Path | None = None,
    labels_path: Path | None = None,
) -> dict[str, Any]:
    """Compare already-persisted blind output to manual labels, preserving scope."""
    extraction_path = output_dir / "extraction.json"
    if not extraction_path.is_file():
        raise ValueError("persist extraction.json before evaluation")
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    corpus_path = corpus_path or FRESH / "corpus-v1.json"
    labels_path = labels_path or corpus_path.parent / "labels.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    source_cases = {case["id"]: case for case in corpus.get("cases", [])}
    manual_labels = {page["id"]: page for page in labels.get("pages", [])}
    pages = []
    for result in extraction["pages"]:
        case = source_cases.get(result["page_id"])
        label_page = manual_labels.get(result["page_id"])
        if case is None or label_page is None:
            continue
        products = result["candidateProducts"]
        offers = result["candidateOffers"]
        expected = case.get("expected_values", {})
        canonical = case.get("canonical_values", {})
        contract_fields = label_page.get("contract_fields", {})
        field_results: dict[str, Any] = {}

        def compare(
            field: str,
            candidates: list[dict[str, Any]],
            expected_value: Any,
            scope: str = "dom",
        ) -> dict[str, Any]:
            values = _field_values(candidates, field)
            if expected_value is None:
                return {
                    "status": "unknown",
                    "candidate_value_count": len(values),
                    "values": [value for _, value in values],
                }
            if scope != "dom":
                return {
                    "status": "uncomparable_external_scope",
                    "candidate_value_count": len(values),
                    "values": [value for _, value in values],
                }
            target = _norm(expected_value)
            matches = [
                candidate["candidate_id"]
                for candidate, value in values
                if value == target
            ]
            mismatches = [
                candidate["candidate_id"]
                for candidate, value in values
                if value != target
            ]
            if matches:
                status = (
                    "comparable_match"
                    if len(values) == 1
                    else "comparable_match_with_ambiguity"
                )
            elif values:
                status = "comparable_mismatch"
            else:
                status = "absent_from_structured_metadata"
            return {
                "status": status,
                "expected": target,
                "matching_candidates": matches,
                "other_candidate_values": mismatches,
                "candidate_value_count": len(values),
                "values": [value for _, value in values],
            }

        field_results["name"] = compare("name", products, expected.get("name"))
        identity = canonical.get("identity", {})
        identity_value = identity.get("value")
        if identity.get("evidence_scope") == "external_url":
            field_results["identity"] = {
                "status": "uncomparable_external_url_scope",
                "expected_scheme": identity.get("scheme"),
                "structured_candidate_count": len(products),
            }
        elif identity_value is not None:
            matches = []
            seen = 0
            for candidate in products:
                for key in ("sku", "productID"):
                    for item in candidate.get("fields", {}).get(key, []):
                        if isinstance(item.get("value"), (str, int, float)):
                            seen += 1
                            if _norm(item["value"]) == _norm(identity_value):
                                matches.append(candidate["candidate_id"])
            field_results["identity"] = {
                "status": "comparable_match"
                if matches
                else "comparable_mismatch"
                if seen
                else "absent_from_structured_metadata",
                "expected_scheme": identity.get("scheme"),
                "expected": str(identity_value),
                "matching_candidates": matches,
                "structured_identity_value_count": seen,
            }
        else:
            field_results["identity"] = {"status": "unknown"}

        price_display = contract_fields.get("price", {})
        raw_price_values = [
            {
                "candidate_id": candidate["candidate_id"],
                "value": item.get("value"),
                "value_kind": item.get("value_kind"),
                "source": item.get("source"),
            }
            for candidate in offers
            for item in candidate.get("fields", {}).get("price", [])
            if isinstance(item.get("value"), (str, int, float))
        ]
        expected_display = price_display.get("display")
        if price_display.get("status") == "absent":
            display_status = "absent_in_manual_contract"
        elif expected_display is None:
            display_status = "unknown_missing_manual_display"
        elif any(
            str(item["value"]) == str(expected_display) for item in raw_price_values
        ):
            display_status = (
                "exact_raw_display_match"
                if len(raw_price_values) == 1
                else "exact_raw_display_match_with_ambiguity"
            )
        elif raw_price_values:
            display_status = "raw_display_mismatch"
        else:
            display_status = "absent_from_structured_metadata"
        field_results["price_raw_display"] = {
            "status": display_status,
            "expected_display": expected_display,
            "manual_label_status": price_display.get("status", "unknown"),
            "exact_matching_candidates": [
                item["candidate_id"]
                for item in raw_price_values
                if expected_display is not None
                and str(item["value"]) == str(expected_display)
            ],
            "values": raw_price_values,
            "interpretation": (
                "Exact string comparison only; this is independent "
                "of typed amount/currency support."
            ),
        }

        expected_price = canonical.get("price")
        if expected_price:
            full_pairs = []
            partial = []
            uncomparable_amounts = []
            currency_only = []
            ambiguous = []
            price_evidence_candidate_count = 0
            for candidate in offers:
                evidence = candidate.get("monetary_evidence", {})
                if evidence.get("status") != "no_price_evidence":
                    price_evidence_candidate_count += 1
                if evidence.get("status") == "one_price_value_and_explicit_currency":
                    amount = _norm(evidence.get("amount_raw", ""))
                    currency = _norm(evidence.get("currency_raw", ""))
                    numeric_amount = bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", amount))
                    iso_currency = bool(re.fullmatch(r"[A-Z]{3}", currency))
                    if numeric_amount and iso_currency:
                        full_pairs.append((candidate["candidate_id"], amount, currency))
                    else:
                        reason = (
                            "non_numeric_amount"
                            if not numeric_amount
                            else "currency_not_iso_alpha3_in_evaluation_profile"
                        )
                        uncomparable_amounts.append(
                            (candidate["candidate_id"], amount, currency, reason)
                        )
                elif (
                    evidence.get("status") == "partial_amount_without_explicit_currency"
                ):
                    partial.extend(
                        (candidate["candidate_id"], str(amount))
                        for amount in evidence.get("amounts_raw", [])
                    )
                elif evidence.get("status") == "currency_without_amount":
                    currency_only.append(
                        (candidate["candidate_id"], evidence.get("currencies_raw", []))
                    )
                elif (
                    evidence.get("status") == "ambiguous_multiple_amounts_or_currencies"
                ):
                    ambiguous.append(candidate["candidate_id"])
            wanted = (
                _norm(expected_price.get("amount")),
                _norm(expected_price.get("currency")),
            )
            matches = [
                candidate_id
                for candidate_id, amount, currency in full_pairs
                if (amount, currency) == wanted
            ]
            if matches:
                price_status = (
                    "comparable_match"
                    if price_evidence_candidate_count == 1
                    else "comparable_match_with_ambiguity"
                )
            elif uncomparable_amounts:
                price_status = "uncomparable_price_format_or_currency_text"
            elif ambiguous:
                price_status = "ambiguous_multiple_amounts_or_currencies"
            elif partial:
                price_status = "partial_amount_without_currency"
            elif currency_only:
                price_status = "partial_currency_without_amount"
            elif full_pairs:
                price_status = "comparable_mismatch"
            else:
                price_status = "absent_from_structured_metadata"
            field_results["price_amount_currency"] = {
                "status": price_status,
                "expected": {"amount": wanted[0], "currency": wanted[1]},
                "full_pairs": [
                    {"candidate_id": cid, "amount": amount, "currency": currency}
                    for cid, amount, currency in full_pairs
                ],
                "amount_only": [
                    {"candidate_id": cid, "amount": amount} for cid, amount in partial
                ],
                "currency_only": [
                    {"candidate_id": cid, "currencies": values}
                    for cid, values in currency_only
                ],
                "uncomparable_price_values": [
                    {
                        "candidate_id": cid,
                        "amount": amount,
                        "currency": currency,
                        "reason": reason,
                    }
                    for cid, amount, currency, reason in uncomparable_amounts
                ],
                "ambiguous_candidates": ambiguous,
            }
        else:
            field_results["price_amount_currency"] = {"status": "unknown"}

        stock_values = [
            entry for offer in offers for entry in offer.get("availability", [])
        ]
        field_results["stock"] = {
            "status": "uncomparable_enum_vs_stock_prose_or_quantity"
            if stock_values
            else "absent_from_structured_metadata",
            "manual_value": expected.get("stock"),
            "availability": stock_values,
            "note": (
                "A Schema.org availability URI records an enum "
                "state; it does not encode stock quantity or "
                "establish current inventory."
            ),
        }
        for field in ("color", "material"):
            values = _field_values(products, field)
            label_status = case.get("expected_status", {}).get(field, "unknown")
            if label_status == "absent" and not values:
                status = "absent_in_manual_dom_label_and_structured_metadata"
            elif label_status == "absent" and values:
                status = "uncomparable_hidden_metadata_when_manual_dom_label_absent"
            else:
                status = "uncomparable_manual_annotation_scope"
            field_results[field] = {
                "status": status,
                "values": [value for _, value in values],
            }
        pages.append(
            {
                "page_id": result["page_id"],
                "extraction_status": result["status"],
                "product_candidate_count": len(products),
                "offer_candidate_count": len(offers),
                "fields": field_results,
            }
        )
    evaluation = {
        "format": "product-retrieval-structured-evaluation-v1",
        "evaluated_after_extraction_persisted": True,
        "extraction_sha256": hashlib.sha256(extraction_path.read_bytes()).hexdigest(),
        "manual_corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "manual_labels_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "manual_label_annotation_status": labels.get("annotation_status"),
        "annotation_scope": (
            "manual labels describe captured page evidence; "
            "embedded source metadata may be hidden and is "
            "evaluated separately"
        ),
        "operator_prior_label_inspection": True,
        "pages": pages,
    }
    (output_dir / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    counts: dict[str, dict[str, int]] = {}
    page_statuses: dict[str, int] = {}
    product_count = sum(len(page["candidateProducts"]) for page in extraction["pages"])
    offer_count = sum(len(page["candidateOffers"]) for page in extraction["pages"])
    for page in pages:
        page_statuses[page["extraction_status"]] = (
            page_statuses.get(page["extraction_status"], 0) + 1
        )
        for field, item in page["fields"].items():
            bucket = counts.setdefault(field, {})
            bucket[item["status"]] = bucket.get(item["status"], 0) + 1
    lines = [
        "# Structured product metadata: bounded extraction results",
        "",
        (
            f"Pages: {len(pages)}; {product_count} Product and "
            f"{offer_count} Offer candidates; extraction statuses: "
            f"{page_statuses}; CPU: {extraction['cpu_seconds']:.6f}s."
        ),
        "",
        (
            "Method note: the extractor code read only the "
            "source manifest and saved HTML, but the operator "
            "inspected sample corpus/label values during setup "
            "before the extraction run. This is not a blind "
            "operator evaluation."
        ),
        "",
        (
            "Per-page limits: 2 MiB source HTML; 256 KiB per "
            "JSON-LD script; 5,000 HTML element nodes; 5,000 "
            "JSON objects; nesting depth 64."
        ),
        "",
        (
            "This compares already-persisted source-HTML "
            "extraction with the manual corpus. The manual "
            "labels describe page evidence; JSON-LD and "
            "microdata may be hidden metadata. A structured "
            "value does not prove visible content, current "
            "availability, or semantic truth."
        ),
        "",
        "| Field | Evaluation statuses |",
        "| --- | --- |",
    ]
    for field, statuses in sorted(counts.items()):
        lines.append(
            f"| {field} | "
            + ", ".join(f"{key}: {value}" for key, value in sorted(statuses.items()))
            + " |"
        )
    lines.extend(
        [
            "",
            (
                "The extractor preserves multiple Product and Offer "
                "candidates. It recognizes only explicit Schema.org "
                "availability URIs; availability is not stock "
                "quantity or stock prose. An amount without an "
                "explicit currency is partial monetary evidence. "
                "Colors/materials absent from manual page labels are "
                "not inferred."
            ),
            "",
            (
                "Price results are split: `price_raw_display` "
                "compares the preserved property string exactly with "
                "`contract_fields.price.display`; "
                "`price_amount_currency` compares a bare numeric "
                "amount and explicit uppercase three-letter currency "
                "separately. A raw display match does not claim the "
                "hidden property is visible, and `$` is never "
                "stripped to manufacture a typed amount."
            ),
            "",
            (
                "Supported fields are Product.name, sku, productID, "
                "color, material and Offer.price, priceCurrency, "
                "availability. Other Schema.org fields and types "
                "(including GTIN/MPN, brand/image, "
                "priceSpecification, shipping, seller, and aggregate "
                "offer prices) are not extracted."
            ),
            "",
            (
                "Unsupported profile: remote JSON-LD contexts are "
                "never fetched; JSON-LD property aliases beyond the "
                "inline Schema.org type subset, HTML5 parse "
                "recovery, microdata itemref, "
                "template/foreign-namespace microdata, nested "
                "PriceSpecification traversal, and browser-rendered "
                "or JavaScript-mutated DOM are not implemented. "
                "Price/currency values are retained raw; evaluation "
                "does not strip currency symbols, infer currencies, "
                "or validate non-ISO formats. Per-page issues and "
                "byte/node provenance are in `extraction.json`."
            ),
            "",
            (
                "Primary references (Schema.org 30.1, published "
                "2026-09-16; WHATWG HTML living standard accessed "
                "2026-10-31):"
            ),
            "- https://schema.org/version/30.1/",
            "- https://schema.org/Product",
            "- https://schema.org/Offer",
            "- https://schema.org/price",
            "- https://html.spec.whatwg.org/multipage/microdata.html",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("extract", "evaluate"))
    parser.add_argument("--fresh", type=Path, default=FRESH)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.command == "extract":
        result = extract_manifest(args.fresh, args.output)
    else:
        result = evaluate_persisted(args.output, args.fresh / "corpus-v1.json")
    print(
        json.dumps(
            {
                "command": args.command,
                "output": str(args.output),
                "pages": len(result.get("pages", [])),
            }
        )
    )


if __name__ == "__main__":
    main()
