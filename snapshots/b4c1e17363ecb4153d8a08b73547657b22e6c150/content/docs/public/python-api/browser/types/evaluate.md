---
title: "Evaluate"
description: "yosoi.browser.Evaluate Python API reference."
order: 0
---

`yosoi.browser.Evaluate`

```python
class Evaluate(TriggerStep):
```

Declare JavaScript evaluation in the browser page.

Execution requires JavaScript permission in the owning Session or managed
invocation. Construction does not execute the source.

Attributes:
    kind: Wire discriminator identifying this declaration.
    source: Nonempty JavaScript source bounded to 65,536 characters.

[Source: python/yosoi/browser.py:257](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L257-L269)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['evaluate'] = 'evaluate'
source: StrictStr = Field(min_length=1, max_length=65536)
```
