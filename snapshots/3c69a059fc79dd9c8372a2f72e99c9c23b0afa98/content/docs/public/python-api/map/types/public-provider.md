---
title: "PublicProvider"
description: "yosoi.map.PublicProvider Python API reference."
order: 0
---

`yosoi.map.PublicProvider`

```python
class PublicProvider(StrEnum):
```

Anonymous historical discovery indexes with fixed endpoint shapes.

Attributes:
    crt_sh: Certificate-transparency names from crt.sh.
    hacker_target: Hostname/address rows from anonymous hostsearch.
    subdomain_center: Names from the anonymous Subdomain Center index.
    wayback_archive: Historical URLs from Wayback CDX. Passive reports do not prove
        current reachability.

[Source: python/yosoi/map.py:90](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/map.py#L90-L197)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
crt_sh = 'crt_sh'
hacker_target = 'hacker_target'
subdomain_center = 'subdomain_center'
wayback_archive = 'wayback_archive'
```

## Methods

### all

```python
@classmethod
def all(cls) -> tuple[PublicProvider, ...]:
```

Return the deterministic catalog order supplied by the Rust SDK.

[Source: python/yosoi/map.py:107](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/map.py#L107-L109)

### name

```python
@property
def name(self) -> str:
```

Return the stable Rust catalog key used in outcomes and provenance.

[Source: python/yosoi/map.py:112](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/map.py#L112-L114)

### endpoint

```python
def endpoint(self, domain: str) -> str:
```

Build a fixed anonymous HTTPS query without network I/O.

Args:
    domain: DNS domain to validate and encode into the provider query.

Returns:
    A fixed endpoint; callers cannot override its host or path.

Raises:
    MapError: The domain is invalid for the provider endpoint shape.

[Source: python/yosoi/map.py:116](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/map.py#L116-L128)
