---
title: "SourceStatus"
description: "yosoi.map.SourceStatus Python API reference."
order: 0
---

`yosoi.map.SourceStatus`

```python
class SourceStatus(ImmutableModel):
```

Per-source processing state, distinct from operation termination.

Attributes:
    kind: completed is supported processing within local limits, not whole-site
        completeness; sampled denotes provider-side limits; truncated denotes local
        loss; skipped, disabled, failed, and not_started retain omitted work.
    value: Skip classification or typed source failure when applicable, otherwise
        None.

[Source: python/yosoi/map.py:398](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L398-L418)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['completed', 'sampled', 'skipped', 'disabled', 'failed', 'truncated', 'not_started']
value: SourceSkipReason | SourceFailure | None = None
```
