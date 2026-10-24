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

[Source: python/yosoi/runtime_contracts.py:101](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L101-L103)
