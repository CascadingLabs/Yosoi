---
title: "PolicySnapshot"
description: "yosoi.policy.PolicySnapshot Python API reference."
order: 0
---

`yosoi.policy.PolicySnapshot`

```python
class PolicySnapshot(ImmutableModel):
```

Deeply frozen Rust-validated authoring and resolved behavior.

Attributes:
    policy: Immutable authored declaration retained at preparation time.
    effective_policy: Immutable Current selections and concrete execution budgets
        resolved by Rust.
    identity: Versioned digest binding this snapshot to resolved behavior.

[Source: python/yosoi/policy.py:1420](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L1420-L1447)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
policy: _SnapshotPolicy
effective_policy: _SnapshotEffectivePolicy
identity: PolicyIdentity
```

## Methods

### from_policy

```python
@classmethod
def from_policy(cls, policy: Policy) -> Self:
```

Freeze a validated authored declaration and its resolved behavior.

Args:
    policy: Editable complete declaration to validate and snapshot now.

Returns:
    A deeply frozen snapshot unaffected by later authoring or registry edits.

Raises:
    PolicyError: Complete declaration or Current selection resolution fails.

[Source: python/yosoi/policy.py:1435](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L1435-L1447)
