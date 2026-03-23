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

    Kept elements are chosen to maximize attribute diversity — so the LLM sees
    the full structural vocabulary (e.g. promo badges, review counts, stock
    status) even when only a subset of items carry those attributes.

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


def _descendant_class_set(tag: Tag) -> frozenset[str]:
    """Collect all CSS class names from a tag and its descendants."""
    classes: set[str] = set()
    for cls in tag.get('class', []):
        classes.add(cls)
    for child in tag.descendants:
        if isinstance(child, Tag):
            for cls in child.get('class', []):
                classes.add(cls)
    return frozenset(classes)


def _select_diverse(group: list[Tag], keep: int) -> list[Tag]:
    """Pick *keep* elements from *group* that maximize class diversity.

    Uses a greedy algorithm: start with the first element (anchor),
    then repeatedly pick the element that adds the most unseen classes.
    """
    if len(group) <= keep:
        return list(group)

    class_sets = [_descendant_class_set(tag) for tag in group]

    # Always include the first element as anchor
    selected_indices: list[int] = [0]
    covered = set(class_sets[0])

    while len(selected_indices) < keep:
        best_idx = -1
        best_new = -1
        for idx, cls_set in enumerate(class_sets):
            if idx in selected_indices:
                continue
            new_count = len(cls_set - covered)
            if new_count > best_new:
                best_new = new_count
                best_idx = idx
        if best_idx == -1:
            break
        selected_indices.append(best_idx)
        covered |= class_sets[best_idx]

    # Fill remaining slots if greedy didn't reach keep (all identical)
    for idx in range(len(group)):
        if len(selected_indices) >= keep:
            break
        if idx not in selected_indices:
            selected_indices.append(idx)

    return [group[i] for i in selected_indices]


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
            group = children[i:j]
            keepers = set(_select_diverse(group, keep))
            for child in group:
                if child not in keepers:
                    child.decompose()
        i = j
