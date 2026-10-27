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

[Source: python/yosoi/policy.py:902](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L902-L912)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: PositiveU16
sha256: Annotated[str, Field(pattern='^[0-9a-f]{64}$')]
```
