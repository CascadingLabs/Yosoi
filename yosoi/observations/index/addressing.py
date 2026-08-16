"""Observation addresses: how a reference is written, parsed, and resolved.

An address must outlive the snapshot that minted it. An absolute element path alone does
not: scroll a virtualised list and `tr[3]` is a different row, expand an accordion and every
following sibling index shifts. A diff across snapshots then compares two addresses that
changed meaning without changing text.

So an address is a **path of segments**, mirroring what `ys.Contract` already means by root:

    //*[@id="prices"]#anchor=id%3Dprices|./tbody#shape=8f3a1c2d&key=id%3Drow-AAPL|./td[2]

Each segment is `path` plus optional `#anchor=…`, `#shape=…`, `&key=…` / `&ordinal=…`:

    ANCHOR   //*[@id="x"]#anchor=id%3Dx    document-unique attribute key; only the FIRST segment
    ELEMENT  ./td[2]                       one exact element, relative to the segment before
    REGION   ./tbody#shape=<hex>           a repeat container; survives scroll
    MEMBER   …#shape=<hex>&key=<key>       durable member of that region
    MEMBER   …#shape=<hex>&ordinal=<n>     positional guess, DECLARED unstable

Segments compose, so an element nested three repeats deep is still addressed by what the
page keeps — containers and content keys — rather than by positions that shift underneath
it.

Two separate properties, and conflating them is how a reference gets trusted further than it
earned:

* `is_stable` — no segment fell back to an `&ordinal=`. Nothing inside this address is a
  positional guess among its siblings.
* `is_anchored` — the first segment starts from a document-unique attribute key rather than
  from `/html/body/…`. Only an anchored address survives an edit ABOVE it; a root-absolute
  path is positional at every step, so inserting one section near the top of the document
  renames everything beneath it.

A snapshot-independent identity (`ref_id`) is minted only when BOTH hold.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from yosoi.observations.anchoring import COMPOSITE_KEY_PREFIX, TAG_KEY_PREFIX, composite_anchor_parts
from yosoi.observations.anchoring import SAFE_TAG as _SAFE_TAG
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.index import IndexEntry, ObservationIndex
from yosoi.observations.models.view import RegionRef

SEGMENT_SEPARATOR = '|'

_REF_ID_BYTES = 8
"""Identity digest width. Part of the identity contract: changing it invalidates stored ids."""

_POSITIONAL_STEP = re.compile(r'\[\d+\]')
"""An XPath step that selects by sibling position, e.g. `div[3]`."""


class ObservationAddressError(LookupError):
    """Raised when an observation reference is stale, foreign, malformed, or absent."""


def anchor_xpath(anchor: str) -> str:
    """Return the path an anchor key implies: `id=main` → `//*[@id="main"]`, `tag:title` → `//title`.

    The key is carried in the locator alongside the path it implies, and the two are checked
    against each other on parse. Redundant on purpose: the path is what resolves, the key is
    what a diff and a stable identity are computed from, and a locator that disagrees with
    itself must fail rather than pick one.
    """
    if anchor.startswith(TAG_KEY_PREFIX):
        tag = anchor[len(TAG_KEY_PREFIX) :]
        if not tag or not _SAFE_TAG.fullmatch(tag):
            raise ObservationAddressError(f'malformed observation tag anchor {anchor!r}')
        return f'//{tag}'
    if anchor.startswith(COMPOSITE_KEY_PREFIX):
        parts = composite_anchor_parts(anchor)
        if not parts or any(not _SAFE_TAG.fullmatch(name) or '"' in value for name, value in parts):
            raise ObservationAddressError(f'malformed observation composite anchor {anchor!r}')
        predicate = ' and '.join(f'@{name}="{value}"' for name, value in parts)
        return f'//*[{predicate}]'
    name, separator, value = anchor.partition('=')
    if not separator or not name or not _SAFE_TAG.fullmatch(name):
        raise ObservationAddressError(f'malformed observation anchor {anchor!r}')
    if '"' in value:
        raise ObservationAddressError('an anchor value containing a double quote cannot be expressed as a path')
    return f'//*[@{name}="{value}"]'


@dataclass(frozen=True, slots=True)
class AddressSegment:
    """One hop of an address: a path, optionally selecting a member of a repeat region."""

    path: str
    shape: str | None = None
    key: str | None = None
    ordinal: int | None = None
    anchor: str | None = None

    def __post_init__(self) -> None:
        """Reject segment shapes that have no meaning rather than resolving them loosely."""
        if not self.path:
            raise ObservationAddressError('an observation address segment needs a path')
        if (self.key is not None or self.ordinal is not None) and self.shape is None:
            raise ObservationAddressError('a member segment requires the shape of its region')
        if self.key is not None and self.ordinal is not None:
            raise ObservationAddressError('a segment is keyed or positional, never both')
        if self.ordinal is not None and self.ordinal < 0:
            raise ObservationAddressError('a member ordinal cannot be negative')
        if self.anchor is not None and self.path != anchor_xpath(self.anchor):
            raise ObservationAddressError(f'anchored segment path {self.path!r} disagrees with its anchor key')

    @property
    def selects_member(self) -> bool:
        """Whether this segment picks one member out of a region."""
        return self.key is not None or self.ordinal is not None


@dataclass(frozen=True, slots=True)
class ObservationAddress:
    """A parsed, possibly nested observation address."""

    segments: tuple[AddressSegment, ...]

    def __post_init__(self) -> None:
        """Require an absolute first segment and relative ones after it."""
        if not self.segments:
            raise ObservationAddressError('an observation address needs at least one segment')
        if not self.segments[0].path.startswith('/'):
            raise ObservationAddressError(f'the first address segment must be absolute: {self.segments[0].path!r}')
        for segment in self.segments[1:]:
            if not segment.path.startswith('.'):
                raise ObservationAddressError(f'a nested address segment must be relative: {segment.path!r}')
        for segment in self.segments[:-1]:
            if segment.shape is not None and not segment.selects_member:
                raise ObservationAddressError('only the final segment may address a region rather than an element')
        for segment in self.segments[1:]:
            if segment.anchor is not None:
                raise ObservationAddressError('only the first address segment may be anchored')

    @property
    def is_region(self) -> bool:
        """Whether this addresses a repeat container rather than one element or member."""
        last = self.segments[-1]
        return last.shape is not None and not last.selects_member

    @property
    def is_stable(self) -> bool:
        """Whether no segment of this address is a positional guess among siblings."""
        return all(segment.ordinal is None for segment in self.segments)

    @property
    def is_anchored(self) -> bool:
        """Whether this address starts from a document-unique key instead of the root.

        Not the same question as `is_stable`, and the difference is the whole point: a keyed
        member of a region reached through `/html/body/div[2]/…` has no positional guess in it
        anywhere, and still stops meaning the same thing when a sibling appears above `div[2]`.
        """
        return self.segments[0].anchor is not None

    @property
    def is_positional_free(self) -> bool:
        """Whether no step of any segment path selects a sibling by its position.

        The third property, and the one easiest to forget: an address can be anchored to a
        unique `id` and keyed at every region, and still contain `./div[3]/p` below the anchor.
        That `[3]` is a positional guess wearing a durable address's clothes — insert a sibling
        inside the anchor's subtree and it names something else without the locator changing.
        """
        return not any(_POSITIONAL_STEP.search(segment.path) for segment in self.segments)

    def as_region(self, shape: str) -> ObservationAddress:
        """Return this element address reinterpreted as the repeat container it names."""
        last = self.segments[-1]
        if last.shape is not None:
            raise ObservationAddressError('address already names a region')
        return ObservationAddress(
            segments=(*self.segments[:-1], AddressSegment(path=last.path, shape=shape, anchor=last.anchor))
        )

    def region(self) -> ObservationAddress:
        """Return the region address whose member this address selects."""
        last = self.segments[-1]
        if not last.selects_member:
            raise ObservationAddressError('address does not select a region member')
        stripped = AddressSegment(path=last.path, shape=last.shape, anchor=last.anchor)
        return ObservationAddress(segments=(*self.segments[:-1], stripped))

    def member(self, *, key: str | None, ordinal: int | None) -> ObservationAddress:
        """Return the address of one member of this region."""
        if not self.is_region:
            raise ObservationAddressError('only a region address has members')
        last = self.segments[-1]
        selected = AddressSegment(path=last.path, shape=last.shape, key=key, ordinal=ordinal, anchor=last.anchor)
        return ObservationAddress(segments=(*self.segments[:-1], selected))

    def member_segments(self) -> tuple[int, ...]:
        """Return the positions of segments that select a member of a region."""
        return tuple(index for index, segment in enumerate(self.segments) if segment.selects_member)

    def rebind_member(self, key: str, *, at: int = 0) -> ObservationAddress:
        """Return this address with one member selection swapped for another member's key.

        The pruner descends into ONE exemplar per region, so everything the index says about a
        nested structure is said in addresses minted while looking at the first member. Without
        rebinding, an agent can see that team 1-1 has a table of rows and has no way to say "the
        same table, in team 3-4" — its only remaining move is to inspect the whole subtree as
        bytes, which is the thing bounded navigation exists to avoid.

        This is pure address arithmetic. Whether the rebound address actually resolves is a
        question for the inspector against exact bytes, and it fails closed there.
        """
        positions = self.member_segments()
        if at >= len(positions):
            raise ObservationAddressError(f'address selects {len(positions)} member(s); cannot rebind member {at}')
        index = positions[at]
        target = self.segments[index]
        rebound = AddressSegment(path=target.path, shape=target.shape, key=key, anchor=target.anchor)
        return ObservationAddress(segments=(*self.segments[:index], rebound, *self.segments[index + 1 :]))

    def descend(self, relative_path: str) -> ObservationAddress:
        """Return the address of a node inside this one, addressed relative to it."""
        return ObservationAddress(segments=(*self.segments, AddressSegment(path=relative_path)))

    def descend_region(self, relative_path: str, shape: str) -> ObservationAddress:
        """Return the address of a repeat container nested inside this one."""
        return ObservationAddress(segments=(*self.segments, AddressSegment(path=relative_path, shape=shape)))


def _format_segment(segment: AddressSegment) -> str:
    """Serialise one segment to its canonical form."""
    qualifiers: list[str] = []
    if segment.anchor is not None:
        qualifiers.append(f'anchor={quote(segment.anchor, safe="")}')
    if segment.shape is not None:
        qualifiers.append(f'shape={segment.shape}')
        if segment.key is not None:
            qualifiers.append(f'key={quote(segment.key, safe="")}')
        elif segment.ordinal is not None:
            qualifiers.append(f'ordinal={segment.ordinal}')
    if not qualifiers:
        return segment.path
    return f'{segment.path}#{"&".join(qualifiers)}'


def _parse_segment(text: str) -> AddressSegment:
    """Parse one segment, failing closed on anything unrecognised."""
    path, separator, qualifiers = text.partition('#')
    if not separator:
        return AddressSegment(path=path)

    fields: dict[str, str] = {}
    for part in qualifiers.split('&'):
        name, has_value, value = part.partition('=')
        if not has_value or name in fields:
            raise ObservationAddressError(f'malformed observation address qualifier {part!r}')
        fields[name] = value

    unknown = set(fields) - {'anchor', 'shape', 'key', 'ordinal'}
    if unknown:
        raise ObservationAddressError(f'unknown observation address qualifier(s) {sorted(unknown)}')

    raw_ordinal = fields.get('ordinal')
    try:
        ordinal = int(raw_ordinal) if raw_ordinal is not None else None
    except ValueError as exc:
        raise ObservationAddressError(f'observation address ordinal {raw_ordinal!r} is not an integer') from exc

    key = fields.get('key')
    anchor = fields.get('anchor')
    return AddressSegment(
        path=path,
        shape=fields.get('shape'),
        key=unquote(key) if key is not None else None,
        ordinal=ordinal,
        anchor=unquote(anchor) if anchor is not None else None,
    )


def format_address(address: ObservationAddress) -> str:
    """Serialise an address to its canonical locator string."""
    return SEGMENT_SEPARATOR.join(_format_segment(segment) for segment in address.segments)


def parse_address(locator: str) -> ObservationAddress:
    """Parse a locator string, failing closed on anything unrecognised."""
    return ObservationAddress(segments=tuple(_parse_segment(part) for part in locator.split(SEGMENT_SEPARATOR)))


def element_address(absolute_path: str) -> ObservationAddress:
    """Return a plain single-segment address for one exact element."""
    return ObservationAddress(segments=(AddressSegment(path=absolute_path),))


def region_address(container_path: str, shape: str) -> ObservationAddress:
    """Return an address for a repeat container identified by its child shape."""
    return ObservationAddress(segments=(AddressSegment(path=container_path, shape=shape),))


def anchor_address(anchor: str, relative_path: str | None = None) -> ObservationAddress:
    """Return an address rooted at a document-unique key, optionally descending into it."""
    root = AddressSegment(path=anchor_xpath(anchor), anchor=anchor)
    if relative_path is None:
        return ObservationAddress(segments=(root,))
    return ObservationAddress(segments=(root, AddressSegment(path=relative_path)))


def ref_id(modality: EvidenceKind, locator: str) -> str | None:
    """Return a snapshot-independent identity for a locator, or None if it hasn't earned one.

    This is the value a diff matches on and an archived strategy is filed under, so it is
    computed from what the PAGE provides — modality, anchor key, structural shape, member key,
    local path — and from nothing the CAPTURE provides. No snapshot id, no artifact digest:
    two captures of the same unchanged page must produce the same identity or the whole
    archive can only ever compare a snapshot with itself.

    All three properties are required: anchored, no member ordinals, no positional steps. Any
    one of them missing returns None rather than a weaker id. Such a locator still resolves
    exactly within its own snapshot — it simply cannot claim to name the same thing in the next
    one, and an id that silently means "probably the same" is the failure this package is built
    to avoid.
    """
    address = parse_address(locator)
    if not (address.is_stable and address.is_anchored and address.is_positional_free):
        return None
    canonical = f'{modality.value}|{format_address(address)}'
    return hashlib.blake2b(canonical.encode(), digest_size=_REF_ID_BYTES).hexdigest()


def resolve_index_entry(index: ObservationIndex, ref: RegionRef) -> IndexEntry:
    """Resolve an exact reference from a flat index without fuzzy fallback."""
    if ref.snapshot_id != index.snapshot_id:
        raise ObservationAddressError('observation reference belongs to a different snapshot')
    matches = [entry for entry in index.entries if entry.ref == ref]
    if len(matches) != 1:
        raise ObservationAddressError(f'observation reference resolved to {len(matches)} index entries')
    return matches[0]


__all__ = [
    'SEGMENT_SEPARATOR',
    'AddressSegment',
    'ObservationAddress',
    'ObservationAddressError',
    'anchor_address',
    'anchor_xpath',
    'element_address',
    'format_address',
    'parse_address',
    'ref_id',
    'region_address',
    'resolve_index_entry',
]
