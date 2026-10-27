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

[Source: python/yosoi/policy.py:1580](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L1580-L1607)

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

[Source: python/yosoi/policy.py:1595](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L1595-L1607)
