---
title: "BrowserExecutionIdentity"
description: "yosoi.browser.BrowserExecutionIdentity Python API reference."
order: 0
---

`yosoi.browser.BrowserExecutionIdentity`

```python
class BrowserExecutionIdentity(ImmutableModel):
```

Keep controller, engine claims and owned executable facts distinct.

An endpoint, selected profile or user agent does not attest a remote server.
This immutable evidence grants no live browser authority.

Attributes:
    controller_version: Linked controller version when recorded.
    capability_profile: Selected versioned controller capability contract.
    reported_headless: Native server's headless claim when supplied.
    engine: Implementation selected by the caller.
    protocol: Actual controller transport.
    reported_name: Browser name supplied by native session negotiation.
    reported_version: Browser version supplied by native session negotiation.
    executable_version: Admitted owned executable's release version.
    executable_sha256: Owned executable digest, absent for remote services.
    process_owned: Whether this execution owned the process and logical contexts.
    moli_profile: Declared Moli DOM or layout profile, absent for other engines.
    moli_resources: Declared Moli resource profile, absent for other engines.
    owned_moli_private_network_blocking: Native flag in an owned Moli launch;
        remote enforcement has no client attestation here.

[Source: python/yosoi/browser.py:857](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L857-L898)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
controller_version: StrictStr | None = Field(default=None, max_length=512, exclude_if=lambda value: value is None)
capability_profile: StrictStr | None = Field(default=None, max_length=256, exclude_if=lambda value: value is None)
reported_headless: StrictBool | None = Field(default=None, exclude_if=lambda value: value is None)
engine: BrowserEngine
protocol: Literal['cdp', 'bidi']
reported_name: StrictStr | None = None
reported_version: StrictStr | None = None
executable_version: StrictStr | None = None
executable_sha256: str | None = Field(default=None, pattern='^[0-9a-f]{64}$')
process_owned: StrictBool
moli_profile: MoliProfile | None = None
moli_resources: StrictBool | None = None
owned_moli_private_network_blocking: StrictBool | None = None
```
