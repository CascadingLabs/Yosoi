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

[Source: python/yosoi/locators.py:527](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/locators.py#L527-L541)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: OutputId
locator: Locator
```
