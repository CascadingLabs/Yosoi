"""Source-HTML semantic pruning: declarations and structure, as two separate reductions.

Declarations and structure are different problems and get different pruners. Declarations
are a flat list where every entry is unique and worth naming. Structure is a nested tree
whose dominant cost is repetition — a table of 10,000 rows is one shape and 10,000 contents.
Sharing one reducer between them means one of the two gets a representation built for the
other.

The split is by the HTML spec's *metadata content* category, not by `<head>`: a page can
load a script from the end of `<body>`, and books.toscrape does exactly that with jQuery
over plain http. A head-only reducer drops that finding on the floor.

Neither reducer strips classes or ids. Doing so was the worst-performing representation
measured in NEXT-EVAL (arXiv:2505.17125), and they are what Yosoi selectors are made of.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yosoi.observations.html_tree import (
    METADATA_CONTENT,
    SignatureCache,
    assign_member_keys,
    content_children,
    node_label,
    own_text,
    parse,
    skeleton_signature,
    subtree_text,
)
from yosoi.observations.index.addressing import (
    ObservationAddress,
    element_address,
    format_address,
    region_address,
)
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import RegionCoverage
from yosoi.observations.pruning._base import PruneCandidate, Reduction, SemanticPruner, clip
from yosoi.observations.pruning.protocol import PruningPolicy

if TYPE_CHECKING:
    from lxml.etree import _Element, _ElementTree

DECLARATION_PRUNER_VERSION = '1'
BODY_PRUNER_VERSION = '1'

MAX_BODY_DEPTH = 12
"""How deep the body outline descends. Part of the pruner version: change it, bump that."""

MIN_RUN = 2
"""Adjacent siblings sharing a shape become a region at this count. MDR's core rule."""

SAMPLED_MEMBERS = 3
"""How many distinguishing member texts a collapsed region keeps inline."""

_LABEL_VALUE_CHARS = 60
_SAMPLE_TEXT_CHARS = 40


class DeclarationPruner(SemanticPruner):
    """Flat reducer for everything a document DECLARES, wherever it declares it."""

    name = 'html.declarations'
    version = DECLARATION_PRUNER_VERSION
    evidence_kind = EvidenceKind.SOURCE_HTML

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Index the document root plus every metadata-content element, enumerating nothing."""
        root, tree = parse(data)
        declarations = [
            element for element in root.iter() if isinstance(element.tag, str) and element.tag in METADATA_CONTENT
        ]

        label_chars = min(_LABEL_VALUE_CHARS, policy.max_fragment_chars)
        candidates = [
            PruneCandidate(
                locator=format_address(element_address(tree.getpath(root))),
                label='document',
                summary=_document_summary(root),
            )
        ]
        candidates += [
            PruneCandidate(
                locator=format_address(element_address(tree.getpath(element))),
                label=_declaration_label(element, label_chars),
                summary=_declaration_summary(element),
            )
            for element in declarations
        ]
        # The population this pruner considered: the head subtree plus the root it summarises.
        return Reduction(candidates=tuple(candidates), source_items=len(declarations) + 1)


class BodyPruner(SemanticPruner):
    """Structural reducer for body content, collapsing repeated sibling records.

    MDR's rule (Liu et al., 2003): adjacent siblings sharing a structural signature are one
    data region. We use it as a compressor rather than an extractor — its recall-first
    behaviour is a liability when extracting and exactly right when compressing.

    Non-contiguous records (rows split by injected ads or dividers) are DEPTA's problem and
    are not handled; the boss fight asserts that limit rather than leaving it to be
    discovered.
    """

    name = 'html.body'
    version = BODY_PRUNER_VERSION
    evidence_kind = EvidenceKind.SOURCE_HTML

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Walk the body, collapsing repeat regions to container + exemplar + count."""
        root, tree = parse(data)
        body = root.find('.//body')
        if body is None:
            # A fragment artifact has no <body>; its root IS the content subtree.
            body = root

        population = sum(1 for element in body.iter() if isinstance(element.tag, str))
        # The structure root is an entry in its own right: attributes live ON <body> too, and
        # a walk that only ever emits children can never address them.
        candidates: list[PruneCandidate] = [
            PruneCandidate(
                locator=format_address(element_address(tree.getpath(body))),
                label=node_label(body),
                summary=_element_summary(body, 0),
            )
        ]
        _walk(_Anchor(base=None, element=body), tree, depth=0, cache={}, out=candidates, policy=policy)
        return Reduction(candidates=tuple(candidates), source_items=population)


@dataclass(frozen=True)
class _Anchor:
    """How to address nodes beneath the current walk position.

    Inside a repeat, `base` is the durable address of the exemplar MEMBER and every node
    below it is addressed relative to that — so a node three repeats deep is still reached
    through containers and content keys rather than through positions that shift on scroll.
    """

    base: ObservationAddress | None
    element: _Element

    def _relative(self, tree: _ElementTree, node: _Element) -> str:
        anchor_path = tree.getpath(self.element)
        return '.' + tree.getpath(node)[len(anchor_path) :]

    def element_at(self, tree: _ElementTree, node: _Element) -> ObservationAddress:
        """Address one exact element beneath this anchor."""
        if self.base is None:
            return element_address(tree.getpath(node))
        return self.base.descend(self._relative(tree, node))

    def region_at(self, tree: _ElementTree, container: _Element, shape: str) -> ObservationAddress:
        """Address a repeat container beneath this anchor."""
        if self.base is None:
            return region_address(tree.getpath(container), shape)
        return self.base.descend_region(self._relative(tree, container), shape)


def _walk(
    anchor: _Anchor,
    tree: _ElementTree,
    *,
    depth: int,
    cache: SignatureCache,
    out: list[PruneCandidate],
    policy: PruningPolicy,
) -> None:
    """Emit candidates for one node's children, collapsing runs of identical shape."""
    if depth > MAX_BODY_DEPTH:
        return
    from collections import Counter

    children = content_children(anchor.element)
    signatures = [skeleton_signature(child, cache) for child in children]
    runs: list[tuple[str, int]] = []
    cursor = 0
    while cursor < len(children):
        signature = signatures[cursor]
        run = 1
        while cursor + run < len(children) and signatures[cursor + run] == signature:
            run += 1
        runs.append((signature, run))
        cursor += run
    qualifying_runs = Counter(signature for signature, run in runs if run >= MIN_RUN)

    index = 0
    while index < len(children):
        signature = signatures[index]
        run = 1
        while index + run < len(children) and signatures[index + run] == signature:
            run += 1
        exemplar = children[index]
        # A container + shape is one region address. If the same shape forms several
        # separated runs under this container, collapsing each run would mint the same
        # address more than once. Non-contiguous clustering is deliberately out of scope,
        # so preserve those members individually rather than pretending the runs are one.
        collapse = run >= MIN_RUN and qualifying_runs[signature] == 1
        if collapse:
            member = _emit_region(anchor, tree, children[index : index + run], signature, out, policy)
            # Descend into the exemplar only — collapsing and then walking all N would
            # reintroduce the cost the collapse just removed.
            _walk(_Anchor(base=member, element=exemplar), tree, depth=depth + 1, cache=cache, out=out, policy=policy)
        else:
            out.append(
                PruneCandidate(
                    locator=format_address(anchor.element_at(tree, exemplar)),
                    label=node_label(exemplar),
                    summary=_element_summary(exemplar, depth),
                )
            )
            _walk(
                _Anchor(base=anchor.element_at(tree, exemplar) if anchor.base is not None else None, element=exemplar),
                tree,
                depth=depth + 1,
                cache=cache,
                out=out,
                policy=policy,
            )
        index += run if collapse else 1


def _emit_region(
    anchor: _Anchor,
    tree: _ElementTree,
    members: list[_Element],
    signature: str,
    out: list[PruneCandidate],
    policy: PruningPolicy,
) -> ObservationAddress:
    """Emit one region for a run of same-shape siblings plus its exemplar; return the exemplar address.

    The region is the address that survives a scroll; the exemplar shows the shape. The
    other members are reachable through `expand`, never emitted as N entries.
    """
    region = anchor.region_at(tree, anchor.element, signature)
    keys = assign_member_keys(members)
    distinct = list(dict.fromkeys(text for text in (subtree_text(member) for member in members) if text))
    sample_chars = min(_SAMPLE_TEXT_CHARS, policy.max_fragment_chars)
    shown = ', '.join(f'"{clip(text, sample_chars)}"' for text in distinct[:SAMPLED_MEMBERS])
    remainder = len(distinct) - min(SAMPLED_MEMBERS, len(distinct))
    unkeyed = sum(1 for key in keys if key is None)

    summary = f'×{len(members)} {node_label(members[0])}'
    if shown:
        summary += f'  {shown}' + (f' +{remainder} more' if remainder > 0 else '')
    if unkeyed:
        summary += f'  [{unkeyed} member(s) addressable only by position]'

    out.append(
        PruneCandidate(
            locator=format_address(region),
            label=f'{node_label(anchor.element)} > {node_label(members[0])}',
            summary=summary,
            # Static HTML holds every member it has: observed IS declared. A rendered
            # snapshot of a virtualised list will not be able to say this.
            coverage=RegionCoverage(observed=len(members), declared=len(members), complete=True),
        )
    )
    exemplar = region.member(key=keys[0], ordinal=None if keys[0] is not None else 0)
    shape = ', '.join(node_label(child) for child in content_children(members[0])[:8])
    out.append(
        PruneCandidate(
            locator=format_address(exemplar),
            label=node_label(members[0]),
            summary=f'exemplar of ×{len(members)}' + (f'; children: {shape}' if shape else ''),
        )
    )
    return exemplar


def _element_summary(element: _Element, depth: int) -> str:
    """Describe one structural node: its own text, or what it contains, plus any handlers."""
    handlers = sorted(name for name in map(str, element.attrib) if name.startswith('on'))
    suffix = f'  [handlers: {" ".join(handlers)}]' if handlers else ''

    text = own_text(element)
    if text:
        return text + suffix
    children = content_children(element)
    if depth == MAX_BODY_DEPTH and children:
        return f'{len(children)} children (below index depth — inspect to descend){suffix}'
    if children:
        return f'{len(children)} children{suffix}'
    return (subtree_text(element) or '(empty)') + suffix


def _document_summary(root: _Element) -> str:
    """Describe declaration-level facts belonging to the document rather than one element.

    Counts are document-wide on purpose: an attribute vocabulary is only a QA signal if it
    covers the whole page. Absences are stated — a missing `<title>` has no element to
    address, and silence would read as "not checked".
    """
    from collections import Counter

    elements = [element for element in root.iter() if isinstance(element.tag, str)]
    attributes: Counter[str] = Counter()
    handlers: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    for element in elements:
        tags[str(element.tag)] += 1
        for name in element.attrib:
            attributes[str(name)] += 1
            if str(name).startswith('on'):  # HTML spec: event handler content attributes
                handlers[str(name)] += 1

    scripts = [element for element in elements if element.tag == 'script']
    external = [element for element in scripts if element.get('src')]
    sheets = [element for element in elements if element.tag == 'link' and (element.get('rel') or '') == 'stylesheet']

    lang = root.get('lang')
    title = root.findtext('.//title')
    census = ', '.join(f'{tag}:{count}' for tag, count in tags.most_common(20))
    return '; '.join(
        [
            f'lang={lang}' if lang else 'lang=MISSING',
            'title=present' if title is not None else 'title=MISSING',
            f'elements={len(elements)}',
            f'script={len(external)} external/{len(scripts) - len(external)} inline',
            f'stylesheet={len(sheets)}',
            f'attributes={len(attributes)} distinct',
            f'handlers={sorted(handlers)}' if handlers else 'handlers=0',
            f'tags={len(tags)} distinct ({census})',
        ]
    )


def _declaration_label(element: _Element, max_value_chars: int) -> str:
    """Label a declaration by its own first attribute — the author's key, not ours.

    Nothing is enumerated. A `name`/`property`/`http-equiv`/`charset` allowlist can only
    report what it was told to look for; on a real page the spike surfaced
    `<meta name="Andrew Berg">`, a malformed tag any sensible allowlist would have hidden.
    Source attribute order is the author's own statement of what identifies the element.
    """
    tag = str(element.tag)
    attributes = list(element.attrib.items())
    if not attributes:
        return tag
    key, value = attributes[0]
    return f'{tag}[{key}={clip(str(value), max_value_chars)}]'


def _declaration_summary(element: _Element) -> str:
    """Report every remaining attribute and any own text, as found."""
    parts = [f'{name}="{value}"' for name, value in list(element.attrib.items())[1:]]
    text = own_text(element)
    if text:
        parts.append(f'text="{text}"')
    return ' '.join(parts)


__all__ = [
    'BODY_PRUNER_VERSION',
    'DECLARATION_PRUNER_VERSION',
    'MAX_BODY_DEPTH',
    'BodyPruner',
    'DeclarationPruner',
]
