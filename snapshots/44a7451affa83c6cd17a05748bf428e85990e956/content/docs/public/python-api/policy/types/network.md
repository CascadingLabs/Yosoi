---
title: "Network"
description: "yosoi.policy.Network Python API reference."
order: 0
---

`yosoi.policy.Network`

```python
class Network(Model):
```

Opt-in TCP routing retained by Requests and owned browser Sessions.

Attributes:
    ip_family: Permitted socket family, including the connection to a proxy.
    source_address: Already-assigned local IP; does not select a NAT public IP.
    proxy: HTTP(S) CONNECT or SOCKS5 URL. Credentials persist in serialized policy.
        The upstream proxy controls destination DNS and egress family.

[Source: python/yosoi/policy.py:1244](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L1244-L1262)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
model_config = ConfigDict(hide_input_in_errors=True)
ip_family: IpFamily = 'system_default'
source_address: Annotated[str, AfterValidator(_source_address)] | None = Field(default=None, exclude_if=lambda value: value is None)
proxy: str | None = Field(default=None, repr=False, exclude_if=lambda value: value is None)
```
