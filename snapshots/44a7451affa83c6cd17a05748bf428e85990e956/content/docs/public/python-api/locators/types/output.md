---
title: "Output"
description: "yosoi.locators.Output Python API reference."
order: 0
---

`yosoi.locators.Output`

```python
class Output(ImmutableModel):
```

Named projected evidence declaration for a compiled locate plan.

Attributes:
    id: Authored output identity, unique within its plan.
    locator: Query and projection used to produce this output finding evidence.

[Source: python/yosoi/locators.py:527](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/locators.py#L527-L541)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: OutputId
locator: Locator
```
