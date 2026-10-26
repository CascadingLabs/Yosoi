---
title: "ProviderIdentity"
description: "yosoi.search.ProviderIdentity Python API reference."
order: 0
---

`yosoi.search.ProviderIdentity`

```python
class ProviderIdentity(ImmutableModel):
```

Provider and adapter identities recorded when an adapter actually ran.

Attributes:
    provider: Provider selected for this authored policy slot.
    endpoint: Adapter endpoint label, absent when the adapter did not run.
    adapter_version: Adapter implementation version, absent when the adapter did not
        run.
    parser_version: Response parser version, absent when the adapter did not run.

[Source: python/yosoi/search.py:464](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L464-L478)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
provider: Provider
endpoint: str | None
adapter_version: str | None
parser_version: str | None
```
