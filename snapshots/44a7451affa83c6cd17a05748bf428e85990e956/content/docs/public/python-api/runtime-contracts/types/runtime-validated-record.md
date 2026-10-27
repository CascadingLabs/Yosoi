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

[Source: python/yosoi/runtime_contracts.py:136](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L136-L169)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
value: Mapping[str, RuntimeFieldValue]
candidate: RuntimeCandidate
```
