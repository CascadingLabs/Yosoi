---
title: "Matched"
description: "yosoi.outcomes.Matched Python API reference."
order: 0
---

`yosoi.outcomes.Matched`

```python
class Matched(_Outcome):
```

At least one region or finding matched, possibly with partial evidence.

Attributes:
    status: Discriminator fixed to matched for tagged decoding.
    result: Validated nonempty region or finding collection. Inspect finding
        completeness before making absence claims.

[Source: python/yosoi/outcomes.py:979](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L979-L994)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['matched']
result: LocateResult
```

## Methods

### findings

```python
@property
def findings(self) -> tuple[Finding, ...]:
```

Return retained findings in strictly increasing deterministic order.

[Source: python/yosoi/outcomes.py:992](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L992-L994)
