---
title: "FlowPolicy"
description: "yosoi.policy.FlowPolicy Python API reference."
order: 0
---

`yosoi.policy.FlowPolicy`

```python
class FlowPolicy(Model):
```

Independent fallback continuation for failures and cancellations.

Attributes:
    on_failure: Fallback for known step failures unless locally overridden.
    on_cancellation: Fallback for observed cancellation unless locally overridden.
        Unknown effects and unsafe state can force a hard stop.

[Source: python/yosoi/policy.py:1106](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1106-L1122)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
on_failure: Continuation = Field(default_factory=Continue)
on_cancellation: Continuation = Field(default_factory=Continue)
```

## Methods

### is_default

```python
def is_default(self) -> bool:
```

Return whether both fallbacks match Rust's default Continue behavior.

[Source: python/yosoi/policy.py:1118](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1118-L1122)
