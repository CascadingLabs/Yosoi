---
title: "CapturedText"
description: "yosoi.outcomes.CapturedText Python API reference."
order: 0
---

`yosoi.outcomes.CapturedText`

```python
class CapturedText(ImmutableModel):
```

Projected text and named regular-expression capture values.

Attributes:
    text: Full projected text independent of captured subexpressions.
    captures: Capture names mapped to their matched text. The mapping contents
        remain mutable even though model attribute assignment is frozen.

[Source: python/yosoi/outcomes.py:580](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L580-L590)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
text: str
captures: dict[str, str]
```
