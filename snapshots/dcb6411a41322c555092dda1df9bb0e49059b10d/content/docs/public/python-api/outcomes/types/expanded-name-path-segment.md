---
title: "ExpandedNamePathSegment"
description: "yosoi.outcomes.ExpandedNamePathSegment Python API reference."
order: 0
---

`yosoi.outcomes.ExpandedNamePathSegment`

```python
class ExpandedNamePathSegment(ImmutableModel):
```

Namespace-qualified XML element identity within a tree path.

Attributes:
    namespace_uri: Namespace URI independent of source prefix spelling, or None for
        an unqualified name.
    local_name: Retained nonempty local name; no tree membership is checked.
    same_name_sibling_index: One-based index among siblings with the same expanded
        name.

[Source: python/yosoi/outcomes.py:144](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L144-L194)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
namespace_uri: str | None = None
local_name: str
same_name_sibling_index: PositiveU32
```

## Methods

### try_new

```python
@classmethod
def try_new(cls, namespace_uri: str | None, local_name: str, same_name_sibling_index: int) -> Self:
```

Validate an owned XML expanded-name path segment through Rust.

Args:
    namespace_uri: Namespace URI, or None for an unqualified name.
    local_name: Nonempty local element name, independent of prefix spelling.
    same_name_sibling_index: One-based index among same-expanded-name siblings.

Returns:
    A segment without verifying membership in any source tree.

Raises:
    LocatorError: The local name is empty or the sibling index is invalid.

[Source: python/yosoi/outcomes.py:168](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L168-L194)
