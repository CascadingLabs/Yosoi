---
title: "Cardinality"
description: "yosoi.contracts.Cardinality Python API reference."
order: 0
---

`yosoi.contracts.Cardinality`

```python
Cardinality = Literal['exactly_one', 'zero_or_one', 'many']
```

Required accepted field count: exactly one, zero or one, or an ordered collection
including empty. Rust validation enforces these distinctions after extraction.

[Source: python/yosoi/contracts.py:45](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L45-L45)
