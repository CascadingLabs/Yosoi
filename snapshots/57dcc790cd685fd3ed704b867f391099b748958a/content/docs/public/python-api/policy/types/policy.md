---
title: "Policy"
description: "yosoi.policy.Policy Python API reference."
order: 0
---

`yosoi.policy.Policy`

```python
class Policy(Model):
```

Editable complete declaration with Rust-owned defaults and validation.

Attributes:
    default_action_timeout_ms: Positive fallback action duration in milliseconds;
        explicit action/Flow budgets can override it.
    flow: Independent failure/cancellation continuation defaults.
    page: Ordered acquisition declarations and output selections.
    request: Acquisition timing, evidence limits, and redirect behavior.
    documents: Retained-payload parsing limits.
    locators: Query/traversal/finding resource limits.
    tuning: Supported package tuning declaration.
    map: Bounded site discovery scope and budgets.
    search: Ordered search provider selection and shared limits. Later edits are
        rechecked by check, to_json, or snapshot.

[Source: python/yosoi/policy.py:1145](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L1145-L1209)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
default_action_timeout_ms: PositiveU64 = 10000
flow: FlowPolicy = Field(default_factory=FlowPolicy)
page: Page = _field('page')
request: Request = _field('request')
documents: Documents = _field('documents')
locators: Locators = _field('locators')
tuning: Tuning = Field(default_factory=Tuning)
map: Map = _field('map')
search: Search = _field('search')
```

## Methods

### check

```python
def check(self) -> None:
```

Validate this declaration in Rust, including later edits.

[Source: python/yosoi/policy.py:1180](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L1180-L1182)

### to_json

```python
def to_json(self) -> str:
```

Return a Rust-validated declaration, including edits to nested models.

[Source: python/yosoi/policy.py:1184](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L1184-L1186)

### identity

```python
def identity(self) -> PolicyIdentity:
```

Validate and return the Rust identity of resolved policy behavior.

Returns:
    Versioned canonical digest, independent of subsequent caller edits.

Raises:
    PolicyError: Complete policy validation or identity resolution fails.

[Source: python/yosoi/policy.py:1188](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L1188-L1199)

### effective_policy

```python
def effective_policy(self) -> EffectivePolicy:
```

Return Current selections resolved by the Rust policy registry.

[Source: python/yosoi/policy.py:1201](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L1201-L1205)

### snapshot

```python
def snapshot(self) -> PolicySnapshot:
```

Return the immutable Rust-validated declaration and behavior.

[Source: python/yosoi/policy.py:1207](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L1207-L1209)
