---
title: "RuntimeValue"
description: "yosoi.runtime_contracts.RuntimeValue Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeValue`

```python
type RuntimeValue = Annotated[RuntimeString | RuntimeMoneyUsd, Field(discriminator='type')]
```

String or USD Money value tagged by its runtime wire type.

[Source: python/yosoi/runtime_contracts.py:101](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L101-L103)
