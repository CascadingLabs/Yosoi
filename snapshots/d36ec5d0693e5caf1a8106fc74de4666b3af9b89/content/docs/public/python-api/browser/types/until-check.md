---
title: "UntilCheck"
description: "yosoi.browser.UntilCheck Python API reference."
order: 0
---

`yosoi.browser.UntilCheck`

```python
class UntilCheck(ImmutableModel):
```

Retain the state and evidence of one expectation check.

Attributes:
    index: Zero-based check position in the report.
    source: DOM, accessibility, or network evidence source.
    state: Pending, satisfied, rejected, or unavailable evaluation state.
    evidence: Retained evidence; satisfied checks require it.
    error: Optional error bounded to 16,384 UTF-8 bytes.

[Source: python/yosoi/browser.py:1069](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1069-L1091)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
index: U64
source: UntilCheckSource
state: UntilCheckState
evidence: Any | None = None
error: StrictStr | None = None
```
