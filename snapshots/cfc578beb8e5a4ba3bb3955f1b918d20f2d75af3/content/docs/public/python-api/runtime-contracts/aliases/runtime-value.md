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

[Source: python/yosoi/runtime_contracts.py:101](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L101-L103)
