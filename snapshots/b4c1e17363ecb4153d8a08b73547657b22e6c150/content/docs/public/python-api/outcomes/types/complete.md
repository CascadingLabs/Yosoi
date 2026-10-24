---
title: "Complete"
description: "yosoi.outcomes.Complete Python API reference."
order: 0
---

`yosoi.outcomes.Complete`

```python
class Complete(ImmutableModel):
```

Evidence supports complete coverage of the requested locator scope.

Attributes:
    status: Discriminator fixed to complete for tagged decoding. This is a
        scope-specific evidence claim, not whole-site completeness.

[Source: python/yosoi/outcomes.py:521](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L521-L529)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['complete']
```
