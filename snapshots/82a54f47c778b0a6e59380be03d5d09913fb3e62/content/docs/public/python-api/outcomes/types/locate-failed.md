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

[Source: python/yosoi/outcomes.py:1026](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/outcomes.py#L1026-L1035)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['failed']
failure: Failure
```
