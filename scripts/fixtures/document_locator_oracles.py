"""Independent semantic checks for the tiny document-locator oracle matrix."""

from __future__ import annotations

import json
import hashlib
import re
import xml.parsers.expat
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class OracleError(ValueError):
    """A golden locator oracle disagrees with its document."""


HTML_NAMESPACE = "html"
SVG_NAMESPACE = "svg"
MATHML_NAMESPACE = "mathml"
SVG_HTML_INTEGRATION_POINTS = frozenset({"foreignObject", "desc", "title"})
MATHML_TEXT_INTEGRATION_POINTS = frozenset({"mi", "mo", "mn", "ms", "mtext"})
# WHATWG HTML parsing's full SVG tag-name adjustment table (37 entries).
SVG_TAG_NAME_ADJUSTMENTS = {
    "altglyph": "altGlyph",
    "altglyphdef": "altGlyphDef",
    "altglyphitem": "altGlyphItem",
    "animatecolor": "animateColor",
    "animatemotion": "animateMotion",
    "animatetransform": "animateTransform",
    "clippath": "clipPath",
    "feblend": "feBlend",
    "fecolormatrix": "feColorMatrix",
    "fecomponenttransfer": "feComponentTransfer",
    "fecomposite": "feComposite",
    "feconvolvematrix": "feConvolveMatrix",
    "fediffuselighting": "feDiffuseLighting",
    "fedisplacementmap": "feDisplacementMap",
    "fedistantlight": "feDistantLight",
    "fedropshadow": "feDropShadow",
    "feflood": "feFlood",
    "fefunca": "feFuncA",
    "fefuncb": "feFuncB",
    "fefuncg": "feFuncG",
    "fefuncr": "feFuncR",
    "fegaussianblur": "feGaussianBlur",
    "feimage": "feImage",
    "femerge": "feMerge",
    "femergenode": "feMergeNode",
    "femorphology": "feMorphology",
    "feoffset": "feOffset",
    "fepointlight": "fePointLight",
    "fespecularlighting": "feSpecularLighting",
    "fespotlight": "feSpotLight",
    "fetile": "feTile",
    "feturbulence": "feTurbulence",
    "foreignobject": "foreignObject",
    "glyphref": "glyphRef",
    "lineargradient": "linearGradient",
    "radialgradient": "radialGradient",
    "textpath": "textPath",
}


def html_element_namespace(
    parent_namespace: str | None,
    parent_tag: str | None,
    parent_attributes: dict[str, str],
    token_tag: str,
) -> str:
    """Return the namespace assigned by HTML foreign-content start-tag rules."""
    token = token_tag.lower()
    if parent_namespace == SVG_NAMESPACE:
        if parent_tag in SVG_HTML_INTEGRATION_POINTS:
            return html_token_namespace(token)
        return SVG_NAMESPACE
    if parent_namespace == MATHML_NAMESPACE:
        if parent_tag in MATHML_TEXT_INTEGRATION_POINTS:
            if token in {"mglyph", "malignmark"}:
                return MATHML_NAMESPACE
            return html_token_namespace(token)
        if parent_tag == "annotation-xml" and parent_attributes.get(
            "encoding", ""
        ).lower() in {"text/html", "application/xhtml+xml"}:
            return html_token_namespace(token)
        return MATHML_NAMESPACE
    return html_token_namespace(token)


def html_token_namespace(token_tag: str) -> str:
    if token_tag == "svg":
        return SVG_NAMESPACE
    if token_tag == "math":
        return MATHML_NAMESPACE
    return HTML_NAMESPACE


def adjusted_html_element_name(token_tag: str, namespace: str) -> str:
    token = token_tag.lower()
    if namespace == SVG_NAMESPACE:
        return SVG_TAG_NAME_ADJUSTMENTS.get(token, token)
    return token


def normalized_text(value: str) -> str:
    return " ".join(value.split())


@dataclass
class MarkupNode:
    tag: str
    attributes: dict[str, str]
    start: int
    namespace_uri: str | None = None
    parent: MarkupNode | None = None
    end: int | None = None
    children: list[MarkupNode] = field(default_factory=list)
    content: list[str | MarkupNode] = field(default_factory=list)
    path: str = ""
    namespace: str | None = None

    @property
    def expanded_name(self) -> str:
        return f"{{{self.namespace_uri}}}{self.tag}" if self.namespace_uri else self.tag

    def text(self) -> str:
        return normalized_text(
            "".join(part.text() if isinstance(part, MarkupNode) else part for part in self.content)
        )


def assign_paths(root: MarkupNode) -> None:
    root.path = f"/{root.expanded_name}[1]"
    assign_child_paths(root)


def assign_child_paths(parent: MarkupNode) -> None:
    sibling_counts: dict[str, int] = {}
    for child in parent.children:
        index = sibling_counts.get(child.expanded_name, 0) + 1
        sibling_counts[child.expanded_name] = index
        child.path = f"{parent.path}/{child.expanded_name}[{index}]"
        assign_child_paths(child)


def preorder(root: MarkupNode) -> list[MarkupNode]:
    nodes = [root]
    for child in root.children:
        nodes.extend(preorder(child))
    return nodes


class HtmlTreeParser(HTMLParser):
    def __init__(self, data: bytes) -> None:
        super().__init__(convert_charrefs=True)
        try:
            self.source = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise OracleError("golden HTML is not UTF-8") from error
        self.data = data
        self.lines = self.source.splitlines(keepends=True)
        self.line_starts: list[int] = []
        position = 0
        for line in self.lines:
            self.line_starts.append(position)
            position += len(line.encode("utf-8"))
        self.stack: list[MarkupNode] = []
        self.root: MarkupNode | None = None

    def byte_offset(self) -> int:
        line, column = self.getpos()
        try:
            start = self.line_starts[line - 1]
            prefix = self.lines[line - 1][:column]
        except IndexError as error:
            raise OracleError("HTML parser reported an invalid source position") from error
        return start + len(prefix.encode("utf-8"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        parent = self.stack[-1] if self.stack else None
        namespace = html_element_namespace(
            parent.namespace if parent is not None else None,
            parent.tag if parent is not None else None,
            parent.attributes if parent is not None else {},
            tag,
        )
        node = MarkupNode(
            tag=adjusted_html_element_name(tag, namespace),
            attributes=attributes,
            start=self.byte_offset(),
            parent=parent,
            namespace=namespace,
        )
        if parent is None:
            if self.root is not None:
                raise OracleError("golden HTML has more than one root element")
            self.root = node
        else:
            parent.children.append(node)
            parent.content.append(node)
        self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1].tag.lower() != tag.lower():
            raise OracleError(f"golden HTML has mismatched closing tag {tag!r}")
        node = self.stack.pop()
        closing_start = self.byte_offset()
        closing_end = self.data.find(b">", closing_start)
        if closing_end < 0:
            raise OracleError(f"golden HTML closing tag {tag!r} is incomplete")
        node.end = closing_end + 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        node = self.stack.pop()
        end = self.data.find(b">", node.start)
        if end < 0:
            raise OracleError(f"golden HTML self-closing tag {tag!r} is incomplete")
        node.end = end + 1

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1].content.append(data)

    def finish(self) -> MarkupNode:
        if self.stack or self.root is None:
            raise OracleError("golden HTML has an incomplete element tree")
        insert_implied_head(self.root)
        assign_paths(self.root)
        return self.root


class XmlTreeParser:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.stack: list[MarkupNode] = []
        self.root: MarkupNode | None = None
        self.parser = xml.parsers.expat.ParserCreate(namespace_separator="\x1f")
        self.parser.StartElementHandler = self.start
        self.parser.EndElementHandler = self.end
        self.parser.CharacterDataHandler = self.text

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        local_name, namespace_uri = split_expanded_name(tag)
        canonical_attributes = {}
        for name, value in attributes.items():
            local_attribute, attribute_namespace = split_expanded_name(name)
            canonical_name = (
                f"{{{attribute_namespace}}}{local_attribute}"
                if attribute_namespace
                else local_attribute
            )
            canonical_attributes[canonical_name] = value
        parent = self.stack[-1] if self.stack else None
        node = MarkupNode(
            tag=local_name,
            namespace_uri=namespace_uri,
            attributes=canonical_attributes,
            start=self.parser.CurrentByteIndex,
            parent=parent,
        )
        if parent is None:
            if self.root is not None:
                raise OracleError("golden XML has more than one root element")
            self.root = node
        else:
            parent.children.append(node)
            parent.content.append(node)
        self.stack.append(node)

    def end(self, tag: str) -> None:
        local_name, namespace_uri = split_expanded_name(tag)
        if (
            not self.stack
            or self.stack[-1].tag != local_name
            or self.stack[-1].namespace_uri != namespace_uri
        ):
            raise OracleError(f"golden XML has mismatched closing tag {tag!r}")
        node = self.stack.pop()
        opening_end = markup_tag_end(self.data, node.start)
        if self.data[node.start : opening_end - 1].rstrip().endswith(b"/"):
            node.end = opening_end
            return
        closing_start = self.parser.CurrentByteIndex
        closing_end = self.data.find(b">", closing_start)
        if closing_end < 0:
            raise OracleError(f"golden XML closing tag {tag!r} is incomplete")
        node.end = closing_end + 1

    def text(self, data: str) -> None:
        if self.stack:
            self.stack[-1].content.append(data)

    def finish(self) -> MarkupNode:
        try:
            self.parser.Parse(self.data, True)
        except xml.parsers.expat.ExpatError as error:
            raise OracleError(f"golden XML is invalid: {error}") from error
        if self.stack or self.root is None:
            raise OracleError("golden XML has an incomplete element tree")
        assign_paths(self.root)
        return self.root


def parse_markup(path: Path, document_kind: str) -> MarkupNode:
    data = path.read_bytes()
    if document_kind == "html":
        parser = HtmlTreeParser(data)
        parser.feed(parser.source)
        parser.close()
        return parser.finish()
    return XmlTreeParser(data).finish()


def split_expanded_name(name: str) -> tuple[str, str | None]:
    if "\x1f" not in name:
        return name, None
    namespace_uri, local_name = name.split("\x1f", 1)
    return local_name, namespace_uri


def markup_tag_end(data: bytes, start: int) -> int:
    quote: int | None = None
    for position in range(start, len(data)):
        byte = data[position]
        if quote is not None:
            if byte == quote:
                quote = None
        elif byte in {ord("'"), ord('"')}:
            quote = byte
        elif byte == ord(">"):
            return position + 1
    raise OracleError("golden XML start tag is incomplete")


def parse_css_selector(
    expression: str,
    namespace_bindings: dict[str, str],
) -> tuple[list[tuple[str | None, bool, str | None, str | None, bool]], list[str]]:
    tokens = re.findall(r">|[^>\s]+", expression.strip())
    parts: list[tuple[str | None, bool, str | None, str | None, bool]] = []
    combinators: list[str] = []
    pending_child = False
    for token in tokens:
        if token == ">":
            if not parts or pending_child:
                raise OracleError(f"golden CSS combinator is invalid: {expression!r}")
            pending_child = True
            continue
        if parts:
            combinators.append("child" if pending_child else "descendant")
        match = re.fullmatch(
            r"(?:(?P<prefix>[A-Za-z_][\w.-]*)\|)?(?P<tag>[A-Za-z_][\w-]*|\*)?(?:\.([\w-]+))?(?::([A-Za-z-]+))?",
            token,
        )
        if match is None:
            raise OracleError(f"golden CSS oracle uses unsupported syntax: {expression!r}")
        prefix = match.group("prefix")
        tag = match.group("tag")
        class_name = match.group(3)
        pseudo = match.group(4)
        if tag is None and class_name is None:
            raise OracleError(f"golden CSS oracle uses unsupported syntax: {expression!r}")
        if pseudo not in {None, "first-child"}:
            raise OracleError(f"golden CSS pseudo-class is unsupported: {expression!r}")
        if prefix is None:
            namespace_uri = namespace_bindings.get("")
            any_namespace = "" not in namespace_bindings
        else:
            namespace_uri = namespace_bindings.get(prefix)
            any_namespace = False
            if namespace_uri is None:
                raise OracleError(f"golden CSS prefix {prefix!r} is not bound")
        parts.append((namespace_uri, any_namespace, tag, class_name, pseudo == "first-child"))
        pending_child = False
    if not parts or pending_child or len(combinators) + 1 != len(parts):
        raise OracleError(f"golden CSS selector is incomplete: {expression!r}")
    return parts, combinators


def css_name_matches(
    node: MarkupNode,
    selector: tuple[str | None, bool, str | None, str | None, bool],
) -> bool:
    namespace_uri, any_namespace, tag, class_name, first_child = selector
    namespace_matches = any_namespace or node.namespace_uri == namespace_uri
    classes = node.attributes.get("class", "").split()
    first_child_matches = (
        node.parent is not None
        and bool(node.parent.children)
        and node.parent.children[0] is node
    )
    return (
        (tag is None or tag == "*" or node.tag == tag)
        and namespace_matches
        and (class_name is None or class_name in classes)
        and (not first_child or first_child_matches)
    )


def css_matches(
    node: MarkupNode,
    selector: tuple[list[tuple[str | None, bool, str, str | None, bool]], list[str]],
) -> bool:
    parts, combinators = selector
    if not parts or not css_name_matches(node, parts[-1]):
        return False
    current = node
    part_index = len(parts) - 1
    while part_index > 0:
        combinator_index = part_index - 1
        combinator = combinators[combinator_index]
        part_index = combinator_index
        selector_part = parts[part_index]
        if combinator == "child":
            current = current.parent
            if current is None or not css_name_matches(current, selector_part):
                return False
            continue
        ancestor = current.parent
        matched_ancestor = None
        while ancestor is not None:
            if css_name_matches(ancestor, selector_part):
                matched_ancestor = ancestor
                break
            ancestor = ancestor.parent
        if matched_ancestor is None:
            return False
        current = matched_ancestor
    return True


def xpath_nodes(
    root: MarkupNode,
    nodes: list[MarkupNode],
    expression: str,
    namespace_bindings: dict[str, str],
) -> list[MarkupNode]:
    steps = parse_xpath_steps(expression)
    contexts: list[MarkupNode | None] = [None]
    for axis, source in steps:
        name_source, predicates = split_xpath_step(source)
        name_match = parse_xpath_name_test(name_source, namespace_bindings)
        selected: list[MarkupNode] = []
        for context in contexts:
            if axis == "child":
                groups = [[root] if context is None else list(context.children)]
            else:
                bases: list[MarkupNode | None] = [None, *nodes] if context is None else preorder(context)
                groups = [[root] if base is None else list(base.children) for base in bases]
            for group in groups:
                candidates = [node for node in group if name_match(node)]
                for predicate in predicates:
                    candidates = apply_xpath_predicate(
                        candidates,
                        predicate,
                        namespace_bindings,
                    )
                selected.extend(candidates)
        selected_ids = {id(node) for node in selected}
        contexts = [node for node in nodes if id(node) in selected_ids]
    return [node for node in nodes if any(node is context for context in contexts)]


def parse_xpath_steps(expression: str) -> list[tuple[str, str]]:
    if not expression.startswith("/"):
        raise OracleError(f"golden XPath oracle requires an absolute path: {expression!r}")
    steps = []
    position = 0
    while position < len(expression):
        if expression.startswith("//", position):
            axis = "descendant"
            position += 2
        elif expression.startswith("/", position):
            axis = "child"
            position += 1
        else:
            raise OracleError(f"golden XPath path separator is invalid: {expression!r}")
        start = position
        bracket_depth = 0
        quote = None
        while position < len(expression):
            character = expression[position]
            if quote is not None:
                if character == quote:
                    quote = None
            elif character in {"'", '"'}:
                quote = character
            elif character == "[":
                bracket_depth += 1
            elif character == "]":
                bracket_depth -= 1
                if bracket_depth < 0:
                    raise OracleError(f"golden XPath predicate is invalid: {expression!r}")
            elif character == "/" and bracket_depth == 0:
                break
            position += 1
        if bracket_depth != 0 or quote is not None or position == start:
            raise OracleError(f"golden XPath step is invalid: {expression!r}")
        steps.append((axis, expression[start:position]))
    return steps


def split_xpath_step(source: str) -> tuple[str, list[str]]:
    match = re.match(r"([^\[]+)", source)
    if match is None:
        raise OracleError(f"golden XPath node test is invalid: {source!r}")
    name = match.group(1)
    predicates = re.findall(r"\[([^\]]+)\]", source[match.end() :])
    if "".join(f"[{predicate}]" for predicate in predicates) != source[match.end() :]:
        raise OracleError(f"golden XPath predicate syntax is unsupported: {source!r}")
    return name, predicates


def insert_implied_head(root: MarkupNode) -> None:
    if root.tag != "html" or any(child.tag == "head" for child in root.children):
        return
    body = next((child for child in root.children if child.tag == "body"), None)
    head = MarkupNode(
        tag="head",
        attributes={},
        start=0,
        end=0,
        parent=root,
        namespace=HTML_NAMESPACE,
    )
    child_position = root.children.index(body) if body is not None else 0
    root.children.insert(child_position, head)
    content_position = next(
        (index for index, part in enumerate(root.content) if part is body),
        0,
    )
    root.content.insert(content_position, head)


def element_child_path(node: MarkupNode) -> list[int]:
    path: list[int] = []
    current = node
    while current.parent is not None:
        try:
            ordinal = current.parent.children.index(current) + 1
        except ValueError as error:
            raise OracleError("markup parent does not contain its child") from error
        path.append(ordinal)
        current = current.parent
    path.append(1)
    path.reverse()
    return path


def source_tree_coordinate(node: MarkupNode) -> dict[str, Any]:
    return {
        "kind": "source_tree_path",
        "child_path": element_child_path(node),
        "path": node.path,
    }


def validate_svg_tag_name_adjustments() -> None:
    """Exercise the full HTML5 SVG adjustment map and integration-point scope."""
    if len(SVG_TAG_NAME_ADJUSTMENTS) != 37:
        raise OracleError("SVG tag-name adjustment table is incomplete")
    adjusted_tags = "".join("<" + name + "/>" for name in SVG_TAG_NAME_ADJUSTMENTS)
    source = (
        "<html><body><svg>"
        f"{adjusted_tags}"
        "<foreignobject><feblend></feblend>"
        "<svg><foreignobject/></svg></foreignobject>"
        "<desc><foreignobject/></desc><title></title>"
        "</svg></body></html>"
    ).encode("utf-8")
    parser = HtmlTreeParser(source)
    parser.feed(parser.source)
    parser.close()
    nodes = preorder(parser.finish())
    svg_tags = {node.tag for node in nodes if node.namespace == SVG_NAMESPACE}
    missing = set(SVG_TAG_NAME_ADJUSTMENTS.values()) - svg_tags
    if missing:
        raise OracleError(f"SVG tag adjustments were not applied: {sorted(missing)!r}")
    html_foreign_elements = [
        node
        for node in nodes
        if node.tag == "foreignobject" and node.namespace == HTML_NAMESPACE
    ]
    html_filter_elements = [
        node
        for node in nodes
        if node.tag == "feblend" and node.namespace == HTML_NAMESPACE
    ]
    if len(html_foreign_elements) != 1 or len(html_filter_elements) != 1:
        raise OracleError(
            "SVG name adjustment namespace scope mismatch: "
            f"HTML foreignObject tags={len(html_foreign_elements)}, "
            f"HTML filter tags={len(html_filter_elements)}"
        )
    for integration_point in SVG_HTML_INTEGRATION_POINTS:
        if (
            html_element_namespace(SVG_NAMESPACE, integration_point, {}, "foreignobject")
            != HTML_NAMESPACE
        ):
            raise OracleError(f"SVG integration point did not switch to HTML: {integration_point}")


def parse_xpath_name_test(
    source: str,
    namespace_bindings: dict[str, str],
) -> Any:
    if source == "*":
        return lambda _node: True
    qualified = re.fullmatch(r"([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)", source)
    if qualified is not None:
        prefix, local_name = qualified.groups()
        namespace_uri = namespace_bindings.get(prefix)
        if namespace_uri is None:
            raise OracleError(f"golden XPath prefix {prefix!r} is not bound")
        return lambda node: node.tag == local_name and node.namespace_uri == namespace_uri
    if not re.fullmatch(r"[A-Za-z_][\w.-]*", source):
        raise OracleError(f"golden XPath node test is unsupported: {source!r}")
    return lambda node: node.tag == source and node.namespace_uri is None


def apply_xpath_predicate(
    candidates: list[MarkupNode],
    source: str,
    namespace_bindings: dict[str, str],
) -> list[MarkupNode]:
    position = re.fullmatch(r"[1-9][0-9]*", source)
    if position is not None:
        index = int(source) - 1
        return candidates[index : index + 1]
    local_name = re.fullmatch(r"local-name\(\)\s*=\s*(['\"])(.*?)\1", source)
    if local_name is not None:
        wanted = local_name.group(2)
        return [node for node in candidates if node.tag == wanted]
    attribute = re.fullmatch(
        r"@([A-Za-z_][\w.-]*(?::[A-Za-z_][\w.-]*)?)(?:\s*=\s*(['\"])(.*?)\2)?",
        source,
    )
    if attribute is None:
        raise OracleError(f"golden XPath predicate is unsupported: {source!r}")
    name = attribute.group(1)
    expected = attribute.group(3)
    if ":" in name:
        prefix, local_name = name.split(":", 1)
        namespace_uri = namespace_bindings.get(prefix)
        if namespace_uri is None:
            raise OracleError(f"golden XPath prefix {prefix!r} is not bound")
        canonical_name = f"{{{namespace_uri}}}{local_name}"
    else:
        canonical_name = name
    return [
        node
        for node in candidates
        if canonical_name in node.attributes
        and (expected is None or node.attributes[canonical_name] == expected)
    ]


def ancestry(node: MarkupNode) -> list[str]:
    tags: list[str] = []
    current: MarkupNode | None = node
    while current is not None:
        tags.append(current.expanded_name)
        current = current.parent
    tags.reverse()
    return tags


def minimal_text_nodes(nodes: list[MarkupNode], expression: str) -> list[MarkupNode]:
    return [
        node
        for node in nodes
        if expression in node.text()
        and not any(expression in descendant.text() for descendant in node.children)
    ]


def locate_markup(root: MarkupNode, locator: dict[str, Any]) -> list[MarkupNode]:
    nodes = preorder(root)
    kind = locator.get("kind")
    expression = locator.get("expression")
    if not isinstance(expression, str):
        raise OracleError("golden markup locator expression must be a string")
    namespace_bindings = locator.get("namespace_bindings", {})
    if not isinstance(namespace_bindings, dict) or not all(
        isinstance(prefix, str) and isinstance(uri, str) and uri
        for prefix, uri in namespace_bindings.items()
    ):
        raise OracleError("golden markup namespace bindings must be non-empty string mappings")
    if kind == "css":
        selector = parse_css_selector(expression, namespace_bindings)
        return [node for node in nodes if css_matches(node, selector)]
    if kind == "xpath":
        return xpath_nodes(root, nodes, expression, namespace_bindings)
    if kind == "text":
        return minimal_text_nodes(nodes, expression)
    raise OracleError(f"unsupported golden markup locator: {kind!r}")


def markup_value(node: MarkupNode, projection: dict[str, Any]) -> Any:
    kind = projection.get("kind")
    if kind == "text":
        return node.text()
    if kind == "attribute":
        name = projection.get("name")
        if not isinstance(name, str) or name not in node.attributes:
            raise OracleError(f"golden markup projection names a missing attribute: {name!r}")
        return node.attributes[name]
    if kind == "node_reference":
        return {"path": node.path}
    raise OracleError(f"unsupported golden markup projection: {kind!r}")


def validate_markup_case(path: Path, document_kind: str, case: dict[str, Any]) -> None:
    root = parse_markup(path, document_kind)
    selected = locate_markup(root, case["locator"])
    matches = case["expected"]["matches"]
    expected_paths = [match["coordinate"].get("path") for match in matches]
    if [node.path for node in selected] != expected_paths:
        raise OracleError(f"{case['id']} paths do not equal independent locator results")
    for node, match in zip(selected, matches, strict=True):
        coordinate = match["coordinate"]
        if document_kind == "html":
            if coordinate.get("child_path") != element_child_path(node):
                raise OracleError(f"{case['id']} parser tree path does not bind its selected node")
            if "start" in coordinate or "end" in coordinate:
                raise OracleError(f"{case['id']} repaired HTML nodes cannot claim source bytes")
        else:
            if coordinate.get("start") != node.start or coordinate.get("end") != node.end:
                raise OracleError(f"{case['id']} byte range does not bind its selected node")
            if node.end is None or path.read_bytes()[node.start : node.end].strip() == b"":
                raise OracleError(f"{case['id']} selected node has no source bytes")
        if match["value"] != markup_value(node, case["projection"]):
            raise OracleError(f"{case['id']} value does not equal its selected node projection")


def validate_html_region_case(path: Path, case: dict[str, Any]) -> None:
    root = parse_markup(path, "html")
    region = case["region"]
    region_id = region["id"]
    region_nodes = locate_markup(root, region["locator"])
    if len(region_nodes) != case["expected_region_count"]:
        raise OracleError(f"{case['id']} region count does not match the golden document")
    for output in case["outputs"]:
        actual: list[dict[str, Any]] = []
        for ordinal, region_node in enumerate(region_nodes, start=1):
            selected = locate_markup(region_node, output["locator"])
            for node in selected:
                actual.append(
                    {
                        "region_ordinal": ordinal,
                        "value": markup_value(node, output["projection"]),
                        "coordinate": source_tree_coordinate(node),
                        "parent_region": {
                            "id": region_id,
                            "ordinal": ordinal,
                            "coordinate": source_tree_coordinate(region_node),
                        },
                    }
                )
        expected = output["expected"]
        if expected.get("match_count") != len(expected.get("matches", [])):
            raise OracleError(f"{case['id']} output count does not match its values")
        if actual != expected.get("matches"):
            raise OracleError(f"{case['id']} repeated-region oracle disagrees with the fixture")


def advanced_html_records(path: Path, case: dict[str, Any]) -> list[dict[str, Any]]:
    """Recompute the full locked HTML record stream with network-disabled lxml."""
    try:
        from lxml import etree
    except ImportError as error:
        raise OracleError("advanced HTML validation requires lxml") from error
    try:
        source = path.read_bytes()
        source.decode("utf-8", errors="strict")
        root = etree.fromstring(
            source,
            etree.HTMLParser(encoding="utf-8", no_network=True, recover=True),
        )
    except (OSError, UnicodeError, etree.Error) as error:
        raise OracleError(f"cannot parse advanced HTML fixture {path}: {error}") from error
    if root is None:
        raise OracleError("advanced HTML parser returned no document element")

    coordinates: dict[Any, dict[str, Any]] = {}

    def visit(
        node: Any,
        namespace: str,
        tag_name: str,
        child_path: list[int],
        display_path: str,
    ) -> None:
        coordinates[node] = {
            "kind": "source_tree_path",
            "child_path": child_path,
            "path": display_path,
        }
        element_ordinal = 0
        tag_ordinals: dict[str, int] = {}
        attributes = {str(name): str(value) for name, value in node.attrib.items()}
        for child in node:
            if not isinstance(child.tag, str):
                continue
            element_ordinal += 1
            token_tag = child.tag.rsplit("}", 1)[-1]
            child_namespace = html_element_namespace(
                namespace, tag_name, attributes, token_tag
            )
            child_tag = adjusted_html_element_name(token_tag, child_namespace)
            ordinal = tag_ordinals.get(child_tag, 0) + 1
            tag_ordinals[child_tag] = ordinal
            visit(
                child,
                child_namespace,
                child_tag,
                [*child_path, element_ordinal],
                f"{display_path}/{child_tag}[{ordinal}]",
            )

    root_tag = adjusted_html_element_name(str(root.tag), HTML_NAMESPACE)
    visit(root, HTML_NAMESPACE, root_tag, [1], f"/{root_tag}[1]")

    locator = case.get("locator", {})
    projection = case.get("projection", {})
    kind = locator.get("kind")
    expression = locator.get("expression")
    if kind == "css" and expression == "dfn[id]":
        selected = root.xpath("//dfn[@id]")
    elif kind == "xpath" and expression == "//a[@href]":
        selected = root.xpath("//a[@href]")
    elif kind == "text" and isinstance(expression, str):
        needle = normalize_dom_text(expression)
        matching = {
            node
            for node in root.iter()
            if isinstance(node.tag, str)
            and needle in normalize_dom_text("".join(node.itertext()))
        }
        selected = [
            node
            for node in root.iter()
            if node in matching
            and not any(
                isinstance(child.tag, str) and child in matching for child in node
            )
        ]
    else:
        raise OracleError(f"unsupported advanced HTML locator: {kind!r} {expression!r}")

    records: list[dict[str, Any]] = []
    for node in selected:
        coordinate = coordinates.get(node)
        if coordinate is None:
            raise OracleError("advanced HTML selected a node outside the indexed tree")
        projection_kind = projection.get("kind")
        if projection_kind == "text":
            value: Any = normalize_dom_text("".join(node.itertext()))
        elif projection_kind == "attribute":
            name = projection.get("name")
            if not isinstance(name, str) or node.get(name) is None:
                raise OracleError("advanced HTML selected node lacks projected attribute")
            value = node.get(name)
        elif projection_kind == "node_reference":
            value = {"path": coordinate["path"]}
        else:
            raise OracleError(f"unsupported advanced HTML projection: {projection_kind!r}")
        records.append({"value": value, "coordinate": coordinate})
    return records


def validate_advanced_html_case(
    path: Path, case: dict[str, Any], expected: dict[str, Any]
) -> None:
    actual = advanced_html_records(path, case)
    if expected.get("match_count") != len(actual):
        raise OracleError(f"{case['id']} advanced HTML match count differs from lxml")
    html_record_bytes = json.dumps(
        actual,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if expected.get("records_sha256") != hashlib.sha256(html_record_bytes).hexdigest():
        raise OracleError(f"{case['id']} advanced HTML record digest differs from lxml")
    sample_count = min(3, len(actual))
    if expected.get("first") != actual[:sample_count] or expected.get("last") != actual[-sample_count:]:
        raise OracleError(f"{case['id']} advanced HTML samples differ from lxml")


def node_order(document: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = document["nodes"]
    by_id = {node["id"]: node for node in nodes}
    ordered: list[dict[str, Any]] = []
    pending = [document["root"]]
    visited: set[Any] = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            raise OracleError("DOM/AX fixture contains a cycle or duplicate edge")
        visited.add(node_id)
        node = by_id[node_id]
        ordered.append(node)
        pending.extend(reversed(node["children"]))
    if len(ordered) != len(nodes):
        raise OracleError("DOM/AX fixture contains nodes outside the root tree")
    return ordered


HTML_NAMESPACE_URI = "http://www.w3.org/1999/xhtml"
ASCII_WHITESPACE = frozenset("\t\n\f\r ")


def ascii_lower(value: str) -> str:
    return "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character
        for character in value
    )


def dom_attribute_value(node: dict[str, Any], requested_name: str) -> str | None:
    html_element = node.get("namespace_uri") == HTML_NAMESPACE_URI
    requested = ascii_lower(requested_name) if html_element else requested_name
    for attribute in node.get("attributes", []):
        if attribute["namespace_uri"] != "":
            continue
        name = attribute["name"]
        candidate = ascii_lower(name) if html_element else name
        if candidate == requested:
            return attribute["value"]
    return None


def dom_descendant_text(
    document: dict[str, Any],
    root: dict[str, Any],
    by_id: dict[Any, dict[str, Any]] | None = None,
) -> str:
    by_id = by_id or {node["id"]: node for node in document["nodes"]}
    pending = [root["id"]]
    pieces: list[str] = []
    while pending:
        node = by_id[pending.pop()]
        if node["kind"] == "text":
            pieces.append(node["value"])
        else:
            pending.extend(reversed(node["children"]))
    return normalize_dom_text("".join(pieces))


def normalize_dom_text(value: str) -> str:
    normalized: list[str] = []
    previous_was_space = False
    for character in value:
        if character in ASCII_WHITESPACE:
            if not previous_was_space:
                normalized.append(" ")
            previous_was_space = True
        else:
            normalized.append(character)
            previous_was_space = False
    return "".join(normalized).strip(" ")


def locate_dom_tree_text(
    document: dict[str, Any],
    nodes: list[dict[str, Any]],
    expression: str,
    by_id: dict[Any, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized_expression = normalize_dom_text(expression)
    if not normalized_expression:
        raise OracleError("golden DOM tree-text query cannot be empty")
    by_id = by_id or {node["id"]: node for node in document["nodes"]}
    elements = [node for node in nodes if node["kind"] == "element"]
    matches = {
        node["id"]
        for node in elements
        if normalized_expression in dom_descendant_text(document, node, by_id)
    }
    return [
        node
        for node in elements
        if node["id"] in matches
        and not any(child_id in matches for child_id in node["children"])
    ]


def locate_dom(
    document: dict[str, Any],
    nodes: list[dict[str, Any]],
    locator: dict[str, Any],
    by_id: dict[Any, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    kind = locator.get("kind")
    expression = locator.get("expression")
    if not isinstance(expression, str):
        raise OracleError("golden DOM locator expression must be a string")
    if kind == "css":
        selectors = [selector.strip() for selector in expression.split(",")]
        if not selectors or any(not selector for selector in selectors):
            raise OracleError(f"golden DOM CSS uses unsupported syntax: {expression!r}")
        parsed: list[tuple[str, str | None]] = []
        for selector in selectors:
            match = re.fullmatch(r"([A-Za-z_][\w-]*)(?:\.([\w-]+))?", selector)
            if match is None:
                raise OracleError(f"golden DOM CSS uses unsupported syntax: {expression!r}")
            parsed.append(match.groups())
        return [
            node
            for node in nodes
            if node.get("kind") == "element"
            and any(
                (
                    ascii_lower(node["tag_name"]) == ascii_lower(tag)
                    if node.get("namespace_uri") == HTML_NAMESPACE_URI
                    else node["tag_name"] == tag
                )
                and (
                    class_name is None
                    or class_name
                    in (dom_attribute_value(node, "class") or "").split()
                )
                for tag, class_name in parsed
            )
        ]
    if kind == "xpath":
        match = re.fullmatch(
            r"//([A-Za-z_][\w-]*)(?:\[@([A-Za-z_][\w:.-]*)\])?",
            expression,
        )
        if match is None:
            raise OracleError(f"golden DOM XPath uses unsupported syntax: {expression!r}")
        tag, attribute_name = match.groups()
        return [
            node
            for node in nodes
            if node.get("kind") == "element"
            and (
                ascii_lower(node["tag_name"]) == ascii_lower(tag)
                if node.get("namespace_uri") == HTML_NAMESPACE_URI
                else node["tag_name"] == tag
            )
            and (
                attribute_name is None
                or any(
                    attribute["namespace_uri"] == ""
                    and (
                        ascii_lower(attribute["name"]) == ascii_lower(attribute_name)
                        if node.get("namespace_uri") == HTML_NAMESPACE_URI
                        else attribute["name"] == attribute_name
                    )
                    for attribute in node.get("attributes", [])
                )
            )
        ]
    if kind == "text":
        return locate_dom_tree_text(document, nodes, expression, by_id)
    raise OracleError(f"unsupported golden DOM locator: {kind!r}")


def locate_ax(nodes: list[dict[str, Any]], locator: dict[str, Any]) -> list[dict[str, Any]]:
    kind = locator.get("kind")
    if kind == "role":
        expression = locator.get("expression")
        if not isinstance(expression, str):
            raise OracleError("golden AX role expression must be a string")
        return [node for node in nodes if not node["ignored"] and node["role"] == expression]
    if kind == "accessible_name":
        expression = locator.get("expression")
        if not isinstance(expression, str):
            raise OracleError("golden AX accessible-name expression must be a string")
        return [
            node
            for node in nodes
            if not node["ignored"] and node.get("accessible_name") == expression
        ]
    if kind == "text":
        expression = locator.get("expression")
        if not isinstance(expression, str):
            raise OracleError("golden AX text expression must be a string")
        return [node for node in nodes if not node["ignored"] and node.get("text") == expression]
    if kind == "state":
        name = locator.get("name")
        value = locator.get("value")
        if name not in {"expanded", "focused"} or type(value) is not bool:
            raise OracleError("golden AX state locator must name a supported boolean state")
        return [
            node
            for node in nodes
            if not node["ignored"] and node.get("states", {}).get(name) is value
        ]
    raise OracleError(f"unsupported golden AX locator: {kind!r}")


def document_node_value(
    document_kind: str,
    epoch: Any,
    node: dict[str, Any],
    projection: dict[str, Any],
    document: dict[str, Any],
    by_id: dict[Any, dict[str, Any]] | None = None,
) -> Any:
    kind = projection.get("kind")
    if kind == "text":
        return (
            dom_descendant_text(document, node, by_id)
            if document_kind == "dom"
            else node.get("text")
        )
    if kind == "accessible_name" and document_kind == "ax":
        return node.get("accessible_name")
    if kind == "attribute" and document_kind == "dom":
        name = projection.get("name")
        if not isinstance(name, str):
            raise OracleError("golden DOM attribute projection needs an exact name")
        return dom_attribute_value(node, name)
    if kind == "node_reference":
        return {"document_epoch": epoch, "node_id": node["id"]}
    raise OracleError(f"unsupported golden {document_kind} projection: {kind!r}")


def document_node_records(
    document_kind: str, document: dict[str, Any], case: dict[str, Any]
) -> list[dict[str, Any]]:
    nodes = node_order(document)
    by_id = {node["id"]: node for node in document["nodes"]} if document_kind == "dom" else None
    selected = (
        locate_dom(document, nodes, case["locator"], by_id)
        if document_kind == "dom"
        else locate_ax(nodes, case["locator"])
    )
    records: list[dict[str, Any]] = []
    for node in selected:
        coordinate = {
            "document_epoch": document["document_epoch"],
            "node_id": node["id"],
        }
        if document_kind == "ax":
            coordinate["kind"] = "document_node"
        projected = document_node_value(
            document_kind,
            document["document_epoch"],
            node,
            case["projection"],
            document,
            by_id,
        )
        records.append({"value": projected, "coordinate": coordinate})
    return records


def canonical_records_sha256(records: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_document_node_case(path: Path, document_kind: str, case: dict[str, Any]) -> None:
    document = json_document(path)
    if document_kind == "ax" and case["expected"].get("completeness") != document.get(
        "completeness"
    ):
        raise OracleError(f"{case['id']} expected completeness does not match its tree")
    actual = document_node_records(document_kind, document, case)
    if actual != case["expected"]["matches"]:
        raise OracleError(f"{case['id']} values or coordinates differ from the independent DOM oracle")


def validate_advanced_dom_case(
    path: Path, case: dict[str, Any], expected: dict[str, Any]
) -> None:
    document = json_document(path)
    actual = document_node_records("dom", document, case)
    if expected.get("match_count") != len(actual):
        raise OracleError(f"{case['id']} advanced DOM match count differs from its oracle")
    if expected.get("records_sha256") != canonical_records_sha256(actual):
        raise OracleError(f"{case['id']} advanced DOM record digest differs from its oracle")
    sample_count = min(3, len(actual))
    if expected.get("first") != actual[:sample_count] or expected.get("last") != actual[-sample_count:]:
        raise OracleError(f"{case['id']} advanced DOM samples differ from its oracle")


def json_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise OracleError(f"cannot read node fixture {path}: {error}") from error
    if not isinstance(value, dict):
        raise OracleError(f"node fixture {path} must be an object")
    return value


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def json_pointer_result(document: Any, expression: str) -> list[tuple[str, Any]]:
    if expression == "":
        return [("", document)]
    if not expression.startswith("/"):
        raise OracleError(f"invalid golden JSON Pointer: {expression!r}")
    current = document
    for raw_token in expression[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return []
            current = current[token]
        elif isinstance(current, list):
            if not token.isdecimal():
                return []
            index = int(token)
            if index >= len(current):
                return []
            current = current[index]
        else:
            return []
    return [(expression, current)]


def json_path_results(document: Any, expression: str) -> list[tuple[str, Any]]:
    if not expression.startswith("$"):
        raise OracleError(f"invalid golden JSONPath: {expression!r}")
    tokens: list[tuple[str, str | None]] = []
    position = 1
    token_pattern = re.compile(r"\.([A-Za-z_][\w-]*)|\[\*\]")
    while position < len(expression):
        match = token_pattern.match(expression, position)
        if match is None:
            raise OracleError(f"golden JSONPath uses unsupported syntax: {expression!r}")
        tokens.append(("field", match.group(1)) if match.group(1) else ("wildcard", None))
        position = match.end()

    selected: list[tuple[str, Any]] = [("", document)]
    for kind, field_name in tokens:
        next_selected: list[tuple[str, Any]] = []
        if kind == "field":
            for pointer, value in selected:
                if isinstance(value, dict) and field_name in value:
                    next_selected.append(
                        (f"{pointer}/{pointer_token(field_name)}", value[field_name])
                    )
        else:
            for pointer, value in selected:
                if isinstance(value, list):
                    next_selected.extend(
                        (f"{pointer}/{index}", item) for index, item in enumerate(value)
                    )
        selected = next_selected
    return selected


def validate_json_case(path: Path, case: dict[str, Any]) -> None:
    document = json_document(path)
    locator = case["locator"]
    expression = locator.get("expression")
    if not isinstance(expression, str):
        raise OracleError("golden JSON locator expression must be a string")
    if locator.get("kind") == "json_pointer":
        selected = json_pointer_result(document, expression)
    elif locator.get("kind") == "json_path":
        selected = json_path_results(document, expression)
    else:
        raise OracleError(f"unsupported golden JSON locator: {locator.get('kind')!r}")
    expected = [
        (match["coordinate"].get("pointer"), match["value"])
        for match in case["expected"]["matches"]
    ]
    if selected != expected:
        raise OracleError(f"{case['id']} JSON query results do not equal its coordinates/values")


def literal_text_results(
    data: bytes, expression: str
) -> list[tuple[int, int, int, int, str, dict[str, str]]]:
    needle = expression.encode("utf-8")
    if not needle:
        raise OracleError("golden literal-text query cannot be empty")
    results: list[tuple[int, int, int, int, str, dict[str, str]]] = []
    position = 0
    previous_byte_end = 0
    previous_scalar_end = 0
    while (start := data.find(needle, position)) >= 0:
        end = start + len(needle)
        try:
            gap_scalars = len(data[previous_byte_end:start].decode("utf-8"))
            match_scalars = len(data[start:end].decode("utf-8"))
        except UnicodeDecodeError as error:
            raise OracleError("golden decoded text is not valid UTF-8") from error
        scalar_start = previous_scalar_end + gap_scalars
        scalar_end = scalar_start + match_scalars
        results.append((start, end, scalar_start, scalar_end, expression, {}))
        position = end
        previous_byte_end = end
        previous_scalar_end = scalar_end
    return results


def regex_text_results(
    data: bytes, expression: str, requested_captures: list[str]
) -> list[tuple[int, int, int, int, str, dict[str, str]]]:
    try:
        text = data.decode("utf-8")
        pattern = re.compile(expression)
    except (UnicodeDecodeError, re.error) as error:
        raise OracleError(f"invalid golden decoded-text regex: {error}") from error
    for name in requested_captures:
        if name not in pattern.groupindex:
            raise OracleError(f"regex names an unknown requested capture: {name!r}")
    results: list[tuple[int, int, int, int, str, dict[str, str]]] = []
    previous_character_end = 0
    previous_byte_end = 0
    previous_scalar_end = 0
    for match in pattern.finditer(text):
        gap = text[previous_character_end : match.start()]
        matched = match.group(0)
        scalar_start = previous_scalar_end + len(gap)
        start = previous_byte_end + len(gap.encode("utf-8"))
        scalar_end = scalar_start + len(matched)
        end = start + len(matched.encode("utf-8"))
        captures = {
            name: value
            for name in requested_captures
            if (value := match.group(name)) is not None
        }
        results.append((start, end, scalar_start, scalar_end, matched, captures))
        previous_character_end = match.end()
        previous_byte_end = end
        previous_scalar_end = scalar_end
    return results


def validate_text_case(path: Path, case: dict[str, Any]) -> None:
    data = path.read_bytes()
    locator = case["locator"]
    expression = locator.get("expression")
    if not isinstance(expression, str):
        raise OracleError("golden decoded-text locator expression must be a string")
    if locator.get("kind") == "text":
        selected = literal_text_results(data, expression)
        selected_captures = False
    elif locator.get("kind") == "regex":
        projection = case.get("projection", {})
        selected_captures = projection.get("kind") == "matched_text_with_captures"
        requested_captures = projection.get("names", []) if selected_captures else []
        if not isinstance(requested_captures, list) or not all(
            isinstance(name, str) and name for name in requested_captures
        ):
            raise OracleError("regex capture projection names must be non-empty strings")
        selected = regex_text_results(data, expression, requested_captures)
    else:
        raise OracleError(f"unsupported golden decoded-text locator: {locator.get('kind')!r}")
    expected = [
        (
            match["coordinate"].get("start"),
            match["coordinate"].get("end"),
            match["coordinate"].get("scalar_start"),
            match["coordinate"].get("scalar_end"),
            match["value"],
        )
        for match in case["expected"]["matches"]
    ]
    oracle_selected = [
        (
            start,
            end,
            scalar_start,
            scalar_end,
            text,
            {"captures": captures} if selected_captures else {},
        )
        for start, end, scalar_start, scalar_end, text, captures in selected
    ]
    expected_selected = [
        (
            start,
            end,
            scalar_start,
            scalar_end,
            value["text"] if selected_captures else value,
            {"captures": value["captures"]} if selected_captures else {},
        )
        for start, end, scalar_start, scalar_end, value in expected
    ]
    if oracle_selected != expected_selected:
        raise OracleError(
            f"{case['id']} decoded-text query results do not equal byte/scalar ranges and projections"
        )


def validate_case(path: Path, document_kind: str, case: dict[str, Any]) -> None:
    if document_kind in {"html", "xml"}:
        validate_markup_case(path, document_kind, case)
    elif document_kind == "json":
        validate_json_case(path, case)
    elif document_kind in {"dom", "ax"}:
        validate_document_node_case(path, document_kind, case)
    elif document_kind == "text":
        validate_text_case(path, case)
