---
title: "EffectiveSearch"
description: "yosoi.policy.EffectiveSearch Python API reference."
order: 0
---

`yosoi.policy.EffectiveSearch`

```python
class EffectiveSearch(ImmutableModel):
```

Resolved ordered provider routes and shared search budgets.

Attributes:
    providers: Concrete provider slots in authored order, including unavailable
        routes.
    max_in_flight: Maximum simultaneous provider work.
    max_browser_in_flight: Maximum simultaneous browser-backed provider work.
    max_results_per_provider: Retained organic hits per provider.
    max_total_results: Shared retained-hit capacity.
    max_retained_content_bytes: Shared URL/text retention bytes.
    maximum_elapsed: Shared elapsed budget in microseconds.

[Source: python/yosoi/policy.py:1035](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L1035-L1055)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
providers: tuple[EffectiveProviderRoute, ...]
max_in_flight: PositiveInt
max_browser_in_flight: PositiveInt
max_results_per_provider: PositiveU16
max_total_results: PositiveU32
max_retained_content_bytes: AddressableByteLimit
maximum_elapsed: MaximumElapsed
```
