---
title: "Documents"
description: "yosoi.policy.Documents Python API reference."
order: 0
---

`yosoi.policy.Documents`

```python
class Documents(Model):
```

Retained-payload parsing resource limits.

Attributes:
    max_input_bytes: Positive addressable input payload bytes accepted for parsing.
    max_nodes: Positive maximum parsed node count.
    max_depth: Positive maximum parse/tree depth.

[Source: python/yosoi/policy.py:403](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L403-L414)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_input_bytes: AddressableByteLimitValue = _field('documents', 'max_input_bytes')
max_nodes: CountLimitValue = _field('documents', 'max_nodes')
max_depth: StepLimitValue = _field('documents', 'max_depth')
```
