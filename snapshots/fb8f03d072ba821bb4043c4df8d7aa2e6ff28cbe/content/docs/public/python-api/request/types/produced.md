---
title: "Produced"
description: "yosoi.request.Produced Python API reference."
order: 0
---

`yosoi.request.Produced`

```python
class Produced(ImmutableModel):
```

Requested document representation was produced with retained ownership.

Attributes:
    status: Discriminator fixed to produced for tagged decoding.
    document: Retained immutable document; inspect its locator evidence for
        scope-specific completeness.

[Source: python/yosoi/request.py:94](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/request.py#L94-L104)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['produced']
document: Document
```
