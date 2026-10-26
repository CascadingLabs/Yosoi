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

[Source: python/yosoi/request.py:123](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/request.py#L123-L138)

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

[Source: python/yosoi/request.py:136](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/request.py#L136-L138)
