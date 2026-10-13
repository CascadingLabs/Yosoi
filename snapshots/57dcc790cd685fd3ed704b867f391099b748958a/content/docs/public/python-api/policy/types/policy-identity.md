---
title: "PolicyIdentity"
description: "yosoi.policy.PolicyIdentity Python API reference."
order: 0
---

`yosoi.policy.PolicyIdentity`

```python
class PolicyIdentity(ImmutableModel):
```

Versioned Rust digest identifying effective policy behavior.

Attributes:
    version: Positive identity-format version.
    sha256: Canonical 64-character lowercase hexadecimal digest of the resolved
        policy identity.

[Source: python/yosoi/policy.py:890](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L890-L900)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: PositiveU16
sha256: Annotated[str, Field(pattern='^[0-9a-f]{64}$')]
```
