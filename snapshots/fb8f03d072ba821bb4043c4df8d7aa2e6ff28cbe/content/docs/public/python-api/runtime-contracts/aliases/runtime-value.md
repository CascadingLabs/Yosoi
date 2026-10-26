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

[Source: python/yosoi/runtime_contracts.py:101](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L101-L103)
