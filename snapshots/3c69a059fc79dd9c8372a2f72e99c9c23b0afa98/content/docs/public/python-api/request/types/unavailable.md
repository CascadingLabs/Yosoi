---
title: "Unavailable"
description: "yosoi.request.Unavailable Python API reference."
order: 0
---

`yosoi.request.Unavailable`

```python
class Unavailable(ImmutableModel):
```

Requested evidence was unavailable from the acquisition.

Attributes:
    status: Discriminator fixed to unavailable for tagged decoding.
    reason: Typed explanation for absent evidence, distinct from projection
        incompatibility.

[Source: python/yosoi/request.py:123](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/request.py#L123-L138)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unavailable']
reason: ProjectionReason
```

## Methods

### document

```python
@property
def document(self) -> None:
```

Return None without treating unavailable evidence as complete absence.

[Source: python/yosoi/request.py:136](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/request.py#L136-L138)
