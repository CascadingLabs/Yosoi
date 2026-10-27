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

[Source: python/yosoi/outcomes.py:521](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L521-L529)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['complete']
```
