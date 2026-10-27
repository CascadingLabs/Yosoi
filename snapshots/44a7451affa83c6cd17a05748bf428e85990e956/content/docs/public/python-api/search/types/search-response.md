---
title: "SearchResponse"
description: "yosoi.search.SearchResponse Python API reference."
order: 0
---

`yosoi.search.SearchResponse`

```python
class SearchResponse(ImmutableModel):
```

A cross-provider result retaining failed and unstarted slots.

Attributes:
    request_id: Identity assigned to the authored search.
    policy_identity: Resolved policy identity used for execution.
    termination: completed means the scheduler finished without observed
        cancellation or deadline; individual providers can still fail. cancelled and
        deadline_reached preserve retained outcomes.
    providers: One result per selected provider in authored policy order, not
        completion order.

[Source: python/yosoi/search.py:595](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/search.py#L595-L623)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
request_id: str
policy_identity: PolicyIdentity
termination: Literal['completed', 'cancelled', 'deadline_reached']
providers: tuple[ProviderResult, ...] = Field(repr=False)
```
