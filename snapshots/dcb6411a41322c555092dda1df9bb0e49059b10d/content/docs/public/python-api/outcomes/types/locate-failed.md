---
title: "LocateFailed"
description: "yosoi.outcomes.LocateFailed Python API reference."
order: 0
---

`yosoi.outcomes.LocateFailed`

```python
class LocateFailed(_Outcome):
```

Execution ended with a typed failure instead of a match or absence claim.

Attributes:
    status: Discriminator fixed to failed for tagged decoding.
    failure: Bounded structural failure details without document excerpts.

[Source: python/yosoi/outcomes.py:1026](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L1026-L1035)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['failed']
failure: Failure
```
