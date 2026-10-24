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

[Source: python/yosoi/policy.py:1094](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L1094-L1110)

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

[Source: python/yosoi/policy.py:1106](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L1106-L1110)
