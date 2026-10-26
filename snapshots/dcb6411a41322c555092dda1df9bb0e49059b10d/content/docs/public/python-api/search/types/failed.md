---
title: "Failed"
description: "yosoi.search.Failed Python API reference."
order: 0
---

`yosoi.search.Failed`

```python
class Failed(ImmutableModel):
```

Started provider work ended without a usable normalized response.

Attributes:
    status: Discriminator fixed to failed for tagged decoding.
    value: Failure classification: throttling, access challenge, provider
        availability, malformed or off-query content, transport failure, or
        exhausted output budget.

[Source: python/yosoi/search.py:404](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/search.py#L404-L423)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['failed']
value: Literal['rate_limited', 'challenge', 'provider_unavailable', 'malformed_response', 'query_mismatch', 'transport_failure', 'budget_exhausted']
```
