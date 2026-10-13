---
title: "Summary"
description: "yosoi.map.Summary Python API reference."
order: 0
---

`yosoi.map.Summary`

```python
class Summary(ImmutableModel):
```

Recorded resource accounting and concurrency peaks for a discovery run.

Attributes:
    requests: Charged acquisitions, including support-source requests.
    provider_concurrency_peak: Greatest observed simultaneous public-provider
        acquisitions.
    page_concurrency_peak: Greatest observed simultaneous prefetched page
        acquisitions.
    unused_page_prefetches: Charged speculative page attempts not consumed by
        exploration.
    response_bytes: Aggregate response bytes charged to acquisition budgets.
    inventory_bytes: Bytes charged for retained discovery inventory.
    observations: Count of retained provenance observations.
    omitted: Recorded omission events, not all undiscovered evidence.
    retained_document_bytes: Retained document payload bytes, accounted separately
        from inventory metadata.

[Source: python/yosoi/map.py:548](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/map.py#L548-L575)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
requests: U32 = 0
provider_concurrency_peak: U32 = 0
page_concurrency_peak: U32 = 0
unused_page_prefetches: U32 = 0
response_bytes: U64 = 0
inventory_bytes: U64 = 0
observations: U32 = 0
omitted: U64 = 0
retained_document_bytes: U64 = 0
```
