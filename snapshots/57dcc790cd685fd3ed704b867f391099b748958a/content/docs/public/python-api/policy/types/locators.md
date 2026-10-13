---
title: "Locators"
description: "yosoi.policy.Locators Python API reference."
order: 0
---

`yosoi.policy.Locators`

```python
class Locators(Model):
```

Locator traversal, query, match, and output resource limits.

Attributes:
    max_selector_visits: Positive maximum selector traversal visits.
    max_query_bytes: Positive addressable encoded query metadata bytes.
    max_query_steps: Positive maximum query evaluation steps.
    max_regions: Positive maximum retained repeated-region matches.
    max_matches: Positive maximum retained finding matches.
    max_captures: Positive maximum retained capture values.
    max_output_bytes: Positive addressable bytes retained in locator output.

[Source: python/yosoi/policy.py:417](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L417-L436)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_selector_visits: CountLimitValue = _field('locators', 'max_selector_visits')
max_query_bytes: AddressableByteLimitValue = _field('locators', 'max_query_bytes')
max_query_steps: StepLimitValue = _field('locators', 'max_query_steps')
max_regions: StepLimitValue = _field('locators', 'max_regions')
max_matches: CountLimitValue = _field('locators', 'max_matches')
max_captures: CountLimitValue = _field('locators', 'max_captures')
max_output_bytes: AddressableByteLimitValue = _field('locators', 'max_output_bytes')
```
