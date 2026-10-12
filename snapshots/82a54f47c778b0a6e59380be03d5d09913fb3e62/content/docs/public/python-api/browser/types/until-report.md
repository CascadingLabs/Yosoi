---
title: "UntilReport"
description: "yosoi.browser.UntilReport Python API reference."
order: 0
---

`yosoi.browser.UntilReport`

```python
class UntilReport(ImmutableModel):
```

Retain a typed Until result within the authoritative Flow outcome.

A satisfied report requires supporting check evidence and scope identities. The
enclosing Flow outcome remains authoritative for continuation and cleanup.

Attributes:
    version: Report wire version, currently 1.
    termination: Wait termination, including satisfaction or an explicit
        unsuccessful result.
    scope: Fenced Session, tab, document, frame, and loader identities.
    trigger: Optional receipt from the one-shot action dispatched by Until.
    evaluations: Unsigned count of expectation evaluations.
    checks: One through 128 checks with contiguous zero-based indexes.
    error: Optional report error bounded to 16,384 UTF-8 bytes.

[Source: python/yosoi/browser.py:998](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L998-L1103)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
version: Literal[1]
termination: UntilTermination
scope: UntilScope
trigger: OperationReceipt | None = None
evaluations: U64
checks: tuple[UntilCheck, ...] = Field(min_length=1, max_length=128)
error: StrictStr | None = None
```
