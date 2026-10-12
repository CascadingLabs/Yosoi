---
title: "AccessibilityCoordinate"
description: "yosoi.outcomes.AccessibilityCoordinate Python API reference."
order: 0
---

`yosoi.outcomes.AccessibilityCoordinate`

```python
class AccessibilityCoordinate(ImmutableModel):
```

Accessibility node identity scoped to an immutable snapshot epoch.

Attributes:
    document_epoch: Snapshot epoch needed to interpret the node ID.
    node_id: Retained nonblank accessibility node identity; no live tree membership
        is checked.

[Source: python/yosoi/outcomes.py:318](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/outcomes.py#L318-L356)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_epoch: DocumentEpoch
node_id: str
```

## Methods

### try_new

```python
@classmethod
def try_new(cls, document_epoch: DocumentEpoch, node_id: str) -> Self:
```

Validate accessibility node identity within a supplied epoch.

Args:
    document_epoch: Immutable accessibility-tree snapshot epoch.
    node_id: Nonblank identity whose original spelling is retained.

Returns:
    A coordinate without checking node membership in a live tree.

Raises:
    LocatorError: The node identity is blank or supplied values are invalid.

[Source: python/yosoi/outcomes.py:339](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/outcomes.py#L339-L356)
