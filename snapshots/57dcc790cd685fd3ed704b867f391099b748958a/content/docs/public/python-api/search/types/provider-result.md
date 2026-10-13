---
title: "ProviderResult"
description: "yosoi.search.ProviderResult Python API reference."
order: 0
---

`yosoi.search.ProviderResult`

```python
class ProviderResult(ImmutableModel):
```

One selected provider slot, retained in authored policy order.

Attributes:
    provider: Provider selected for this policy slot.
    identity: Recorded provider and adapter identities.
    profile: Route-selection and effective-policy facts.
    request_id: Underlying Request identity, absent if no Request started.
    recovery_query: Shorter query used for off-query recovery, when attempted; may
        contain user content.
    attempts: Underlying acquisitions, including any recovery Request attempts.
    outcome: Terminal provider interpretation, independent of acquisition success.
    charge: Reported monetary charge facts; unknown does not mean zero.

[Source: python/yosoi/search.py:546](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/search.py#L546-L592)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
provider: Provider
identity: ProviderIdentity
profile: SearchProfileFacts
request_id: str | None
recovery_query: str | None = Field(repr=False)
attempts: tuple[RequestAttemptSummary, ...] = Field(repr=False)
outcome: ProviderOutcome
charge: ProviderCharge
```

## Methods

### hits

```python
@property
def hits(self) -> tuple[SearchHit, ...]:
```

Return organic hits for a results outcome, otherwise an empty tuple.

Use outcome to distinguish an empty response from failure, cancellation, or
unstarted work; this convenience accessor alone cannot establish absence.

[Source: python/yosoi/search.py:586](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/search.py#L586-L592)
