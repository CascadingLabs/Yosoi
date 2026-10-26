---
title: "BrowserConfig"
description: "yosoi.policy.BrowserConfig Python API reference."
order: 0
---

`yosoi.policy.BrowserConfig`

```python
class BrowserConfig(Model):
```

Select a browser implementation without installing or launching it.

Rust validates the complete declaration. Capability never grants arbitrary
JavaScript permission, and an optional engine never silently falls back.

Attributes:
    engine: Chrome/CDP by default, or optional Firefox/Moli native BiDi.
    executable: Absolute installed binary path; omitted paths use engine discovery.
    endpoint: Existing BiDi WebSocket service, mutually exclusive with executable.
        User information, queries and fragments are rejected. Debug repr omits it.
    moli_profile: DOM-only or on-demand layout. Layout is not native headful mode.
    moli_resources: Load optional Moli image/font/media resources deliberately.
    moli_allow_private_networks: Explicit exception to owned Moli's native private
        network blocking. A client cannot attest a shared service's egress policy.

[Source: python/yosoi/policy.py:1138](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L1138-L1183)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
model_config = ConfigDict(hide_input_in_errors=True)
engine: BrowserEngine = 'chrome'
executable: Path | None = None
endpoint: str | None = Field(default=None, repr=False, max_length=4096)
moli_profile: MoliProfile = 'dom'
moli_resources: StrictBool = False
moli_allow_private_networks: StrictBool = False
```

## Methods

### is_default

```python
def is_default(self) -> bool:
```

Return whether canonical policy serialization may omit this declaration.

[Source: python/yosoi/policy.py:1164](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L1164-L1173)
