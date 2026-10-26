---
title: "OperationReceipt"
description: "yosoi.browser.OperationReceipt Python API reference."
order: 0
---

`yosoi.browser.OperationReceipt`

```python
class OperationReceipt(ImmutableModel):
```

Retain observed, rejected, or unknown facts about an operation.

Unknown does not imply that a dispatched operation had no effect. Inspect operation-
specific evidence before claiming business success.

Attributes:
    browser: Native-engine provenance retained even without after-state evidence.
    id: Operation receipt identity.
    kind: Operation kind; Until results carry a validated report.
    status: Whether the operation was observed, rejected, or left unknown.
    result: Operation-specific result payload, or None.
    observation: Optional browser evidence attached to the operation.
    error: Optional retained error detail.

[Source: python/yosoi/browser.py:948](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L948-L1022)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: StrictStr
browser: BrowserExecutionIdentity | None = Field(default=None, exclude_if=lambda value: value is None)
kind: StrictStr
status: OperationStatus
result: Any | None = None
observation: Observation | None = None
error: StrictStr | None = None
```

## Methods

### until_report

```python
def until_report(self) -> UntilReport | None:
```

Parse this Until receipt's immutable result, if it is an Until step.

[Source: python/yosoi/browser.py:1018](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1018-L1022)
