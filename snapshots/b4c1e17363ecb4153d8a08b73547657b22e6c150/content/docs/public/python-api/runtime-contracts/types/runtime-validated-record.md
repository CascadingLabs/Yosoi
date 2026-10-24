---
title: "RuntimeValidatedRecord"
description: "yosoi.runtime_contracts.RuntimeValidatedRecord Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeValidatedRecord`

```python
class RuntimeValidatedRecord(ImmutableModel):
```

Pair accepted field values with their original candidate evidence.

Attributes:
    value: Read-only mapping from schema field IDs to typed cardinality/value
        results.
    candidate: Raw grouped findings from which this record was validated.

[Source: python/yosoi/runtime_contracts.py:151](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L151-L184)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
value: Mapping[str, RuntimeFieldValue]
candidate: RuntimeCandidate
```
