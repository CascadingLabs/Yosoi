"""Observation addresses: how a reference is written, parsed, and resolved.

An address must outlive the snapshot that minted it. An absolute element path alone does
not: scroll a virtualised list and `tr[3]` is a different row, expand an accordion and every
following sibling index shifts. A diff across snapshots then compares two addresses that
changed meaning without changing text.

So an address is a **path of segments**, mirroring what `ys.Contract` already means by root:

    /html/body/table/tbody#shape=8f3a1c2d&key=id%3Drow-AAPL|./td[2]

Each segment is `path` plus optional `#shape=…` and `&key=…` / `&ordinal=…`:

    ELEMENT  ./td[2]                       one exact element, relative to the segment before
    REGION   ./tbody#shape=<hex>           a repeat container; survives scroll
    MEMBER   …#shape=<hex>&key=<key>       durable member of that region
    MEMBER   …#shape=<hex>&ordinal=<n>     positional guess, DECLARED unstable

Segments compose, so an element nested three repeats deep is still addressed by what the
page keeps — containers and content keys — rather than by positions that shift underneath
it. An address is stable iff no segment fell back to an ordinal.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

from yosoi.observations.models.index import IndexEntry, ObservationIndex
from yosoi.observations.models.view import RegionRef

SEGMENT_SEPARATOR = '|'


class ObservationAddressError(LookupError):
    """Raised when an observation reference is stale, foreign, malformed, or absent."""


@dataclass(frozen=True, slots=True)
class AddressSegment:
    """One hop of an address: a path, optionally selecting a member of a repeat region."""

    path: str
    shape: str | None = None
    key: str | None = None
    ordinal: int | None = None

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

    @property
    def is_region(self) -> bool:
        """Whether this addresses a repeat container rather than one element or member."""
        last = self.segments[-1]
        return last.shape is not None and not last.selects_member

    @property
    def is_stable(self) -> bool:
        """Whether this address is expected to survive re-snapshotting the same page."""
        return all(segment.ordinal is None for segment in self.segments)

    def region(self) -> ObservationAddress:
        """Return the region address whose member this address selects."""
        last = self.segments[-1]
        if not last.selects_member:
            raise ObservationAddressError('address does not select a region member')
        stripped = AddressSegment(path=last.path, shape=last.shape)
        return ObservationAddress(segments=(*self.segments[:-1], stripped))

    def member(self, *, key: str | None, ordinal: int | None) -> ObservationAddress:
        """Return the address of one member of this region."""
        if not self.is_region:
            raise ObservationAddressError('only a region address has members')
        last = self.segments[-1]
        selected = AddressSegment(path=last.path, shape=last.shape, key=key, ordinal=ordinal)
        return ObservationAddress(segments=(*self.segments[:-1], selected))

    def descend(self, relative_path: str) -> ObservationAddress:
        """Return the address of a node inside this one, addressed relative to it."""
        return ObservationAddress(segments=(*self.segments, AddressSegment(path=relative_path)))

    def descend_region(self, relative_path: str, shape: str) -> ObservationAddress:
        """Return the address of a repeat container nested inside this one."""
        return ObservationAddress(segments=(*self.segments, AddressSegment(path=relative_path, shape=shape)))


def _format_segment(segment: AddressSegment) -> str:
    """Serialise one segment to its canonical form."""
    if segment.shape is None:
        return segment.path
    text = f'{segment.path}#shape={segment.shape}'
    if segment.key is not None:
        text += f'&key={quote(segment.key, safe="")}'
    elif segment.ordinal is not None:
        text += f'&ordinal={segment.ordinal}'
    return text


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

    unknown = set(fields) - {'shape', 'key', 'ordinal'}
    if unknown:
        raise ObservationAddressError(f'unknown observation address qualifier(s) {sorted(unknown)}')

    raw_ordinal = fields.get('ordinal')
    try:
        ordinal = int(raw_ordinal) if raw_ordinal is not None else None
    except ValueError as exc:
        raise ObservationAddressError(f'observation address ordinal {raw_ordinal!r} is not an integer') from exc

    key = fields.get('key')
    return AddressSegment(
        path=path,
        shape=fields.get('shape'),
        key=unquote(key) if key is not None else None,
        ordinal=ordinal,
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
    'element_address',
    'format_address',
    'parse_address',
    'region_address',
    'resolve_index_entry',
]
