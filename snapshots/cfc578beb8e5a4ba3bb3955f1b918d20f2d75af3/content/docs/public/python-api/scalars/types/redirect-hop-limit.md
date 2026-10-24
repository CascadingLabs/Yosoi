---
title: "RedirectHopLimit"
description: "yosoi.scalars.RedirectHopLimit Python API reference."
order: 0
---

`yosoi.scalars.RedirectHopLimit`

```python
class RedirectHopLimit(ValidatedInteger):
```

Positive u32 bound on Direct HTTP redirect transitions.

[Source: python/yosoi/scalars.py:346](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L346-L354)

## Base classes

[ValidatedInteger](/yosoi/python-api/scalars/types/validated-integer/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### default

```python
@classmethod
def default(cls) -> Self:
```

Return the positive redirect-hop bound selected by Rust defaults.

[Source: python/yosoi/scalars.py:352](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L352-L354)
