---
title: "DomCoordinate"
description: "yosoi.outcomes.DomCoordinate Python API reference."
order: 0
---

`yosoi.outcomes.DomCoordinate`

```python
class DomCoordinate(ImmutableModel):
```

Rendered DOM node identity scoped to one immutable snapshot epoch.

Attributes:
    document_epoch: Snapshot epoch needed to interpret the node ID.
    node_id: Positive snapshot-local identity, without a live DOM membership check.

[Source: python/yosoi/outcomes.py:278](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L278-L315)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_epoch: DocumentEpoch
node_id: DomNodeId
```

## Methods

### new

```python
@classmethod
def new(cls, document_epoch: DocumentEpoch, node_id: DomNodeId) -> Self:
```

Pair a document epoch with a rendered-DOM node identity.

Args:
    document_epoch: Immutable rendered-DOM snapshot epoch.
    node_id: Positive snapshot-local identity.

Returns:
    A coordinate without querying the DOM or verifying snapshot membership.

Raises:
    LocatorError: Supplied values cannot form valid Rust coordinate data.

[Source: python/yosoi/outcomes.py:296](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L296-L315)
