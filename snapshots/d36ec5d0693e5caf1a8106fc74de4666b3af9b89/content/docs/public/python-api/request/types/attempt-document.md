---
title: "AttemptDocument"
description: "yosoi.request.AttemptDocument Python API reference."
order: 0
---

`yosoi.request.AttemptDocument`

```python
class AttemptDocument(ImmutableModel):
```

One authored document request and its typed production outcome.

Attributes:
    requested: Requested response, rendered DOM, accessibility, or network
        representation.
    outcome: Produced, partial, unavailable, or unprojectable evidence, without
        collapsing these states.

[Source: python/yosoi/request.py:168](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/request.py#L168-L179)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
requested: DocumentRequest
outcome: DocumentOutcome
```
