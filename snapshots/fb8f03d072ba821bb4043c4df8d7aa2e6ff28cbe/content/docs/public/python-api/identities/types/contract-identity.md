---
title: "ContractIdentity"
description: "yosoi.identities.ContractIdentity Python API reference."
order: 0
---

`yosoi.identities.ContractIdentity`

```python
class ContractIdentity(str):
```

The hexadecimal representation of a Rust-computed 32-byte identity.

[Source: python/yosoi/identities.py:108](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/identities.py#L108-L129)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### as_bytes

```python
def as_bytes(self) -> bytes:
```

Decode the identity into an owned 32-byte value without recomputing it.

[Source: python/yosoi/identities.py:127](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/identities.py#L127-L129)
