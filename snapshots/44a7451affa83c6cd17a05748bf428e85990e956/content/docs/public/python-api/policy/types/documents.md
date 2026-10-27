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

[Source: python/yosoi/policy.py:415](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L415-L426)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_input_bytes: AddressableByteLimitValue = _field('documents', 'max_input_bytes')
max_nodes: CountLimitValue = _field('documents', 'max_nodes')
max_depth: StepLimitValue = _field('documents', 'max_depth')
```
