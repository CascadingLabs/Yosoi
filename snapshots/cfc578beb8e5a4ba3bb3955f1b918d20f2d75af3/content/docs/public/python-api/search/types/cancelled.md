---
title: "Cancelled"
description: "yosoi.search.Cancelled Python API reference."
order: 0
---

`yosoi.search.Cancelled`

```python
class Cancelled(ImmutableModel):
```

Started provider work observed caller cancellation without rollback.

Attributes:
    status: Discriminator fixed to cancelled for tagged decoding.

[Source: python/yosoi/search.py:426](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L426-L433)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['cancelled']
```
