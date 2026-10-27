---
title: "TerminalFailure"
description: "yosoi.contracts.TerminalFailure Python API reference."
order: 0
---

`yosoi.contracts.TerminalFailure`

```python
class TerminalFailure(ImmutableModel):
```

Structured phase rejection facts, distinct from field issues.

Attributes:
    kind: Classification selecting the applicable rejection details.
    code: Structural plan or parser identifier when present.
    document: Affected class for an unsupported document combination.
    limit: Extraction or validation resource boundary when present.
    maximum: Configured maximum in units of the named resource.
    observed: Recorded or attempted consumption in the same units.
    message: Failure explanation supplied by the native binding, when present.

[Source: python/yosoi/contracts.py:273](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L273-L292)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: str
code: str | None = None
document: str | None = None
limit: str | None = None
maximum: int | None = None
observed: int | None = None
message: str | None = None
```
