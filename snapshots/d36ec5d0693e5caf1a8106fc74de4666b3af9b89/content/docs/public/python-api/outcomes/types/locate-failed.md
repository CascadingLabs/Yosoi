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

[Source: python/yosoi/outcomes.py:1026](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L1026-L1035)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['failed']
failure: Failure
```
