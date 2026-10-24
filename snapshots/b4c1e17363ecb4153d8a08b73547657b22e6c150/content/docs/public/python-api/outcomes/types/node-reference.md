---
title: "NodeReference"
description: "yosoi.outcomes.NodeReference Python API reference."
order: 0
---

`yosoi.outcomes.NodeReference`

```python
class NodeReference(ImmutableModel):
```

Document-bound native location, without retaining document contents.

Attributes:
    document_id: Identity of the document required to interpret this reference.
    coordinate: Native location within that document; construction does not resolve
        it.

[Source: python/yosoi/outcomes.py:479](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L479-L518)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: DocumentId
coordinate: NativeCoordinate
```

## Methods

### new

```python
@classmethod
def new(cls, document_id: DocumentId, coordinate: NativeCoordinate) -> Self:
```

Pair a native location with the document needed to interpret it.

Args:
    document_id: Identity of the retained document.
    coordinate: Native location within that document.

Returns:
    A reference without resolving the coordinate or retaining document contents.

Raises:
    LocatorError: Supplied values cannot form a valid Rust node reference.

[Source: python/yosoi/outcomes.py:498](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L498-L518)
