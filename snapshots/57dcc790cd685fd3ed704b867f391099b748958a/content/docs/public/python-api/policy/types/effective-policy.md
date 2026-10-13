---
title: "EffectivePolicy"
description: "yosoi.policy.EffectivePolicy Python API reference."
order: 0
---

`yosoi.policy.EffectivePolicy`

```python
class EffectivePolicy(ImmutableModel):
```

Rust-resolved behavior view, separate from caller authoring intent.

Attributes:
    default_action_timeout_ms: Positive fallback action duration in milliseconds,
        distinct from request startup budgets.
    flow: Resolved independent failure/cancellation fallback policies.
    page: Resolved acquisitions and output representations.
    request: Acquisition deadlines and evidence limits.
    documents: Parsing byte/node/depth limits.
    locators: Query, traversal, match, capture, and output limits.
    tuning: Resolved package tuning mode.
    map: Resolved discovery scope and resource declaration.
    search: Resolved provider routes and shared budgets.

[Source: python/yosoi/policy.py:1118](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L1118-L1142)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
default_action_timeout_ms: PositiveU64 = 10000
flow: _SnapshotFlowPolicy = Field(default_factory=_SnapshotFlowPolicy)
page: EffectivePage
request: Request
documents: Documents
locators: Locators
tuning: Tuning
map: Map
search: EffectiveSearch
```
