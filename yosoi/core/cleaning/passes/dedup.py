"""Generalized sibling deduplication by structural signature."""

from bs4 import BeautifulSoup, Tag


def deduplicate_siblings(
    soup: BeautifulSoup,
    *,
    min_group: int = 5,
    keep: int = 3,
) -> BeautifulSoup:
    """Deduplicate consecutive siblings that share the same structural signature.

    Groups consecutive child elements by ``(tag_name, sorted_attr_names)`` and
    truncates groups larger than *min_group* to *keep* elements.  This subsumes
    the old list-item and table-row deduplication with a generic approach that
    also handles product cards, review blocks, gallery items, etc.

    Args:
        soup: Parsed HTML tree to deduplicate in-place.
        min_group: Minimum group size before deduplication kicks in.
        keep: Number of siblings to keep per group.

    Returns:
        The same (mutated) soup object.

    """
    for parent in soup.find_all(True):
        if not isinstance(parent, Tag):
            continue
        children = [c for c in parent.children if isinstance(c, Tag)]
        if len(children) < min_group:
            continue
        _dedup_children(children, min_group, keep)
    return soup


def _structural_signature(tag: Tag) -> tuple[str, tuple[str, ...]]:
    """Compute a structural fingerprint for grouping: (tag_name, sorted_attr_names)."""
    return (tag.name, tuple(sorted(tag.attrs.keys())))


def _dedup_children(children: list[Tag], min_group: int, keep: int) -> None:
    """Walk children, group consecutive same-signature elements, and truncate."""
    i = 0
    while i < len(children):
        sig = _structural_signature(children[i])
        # Find the end of the consecutive run with the same signature
        j = i + 1
        while j < len(children) and _structural_signature(children[j]) == sig:
            j += 1
        group_size = j - i
        if group_size >= min_group:
            for child in children[i + keep : j]:
                child.decompose()
        i = j
