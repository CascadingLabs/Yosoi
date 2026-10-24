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
    id: Operation receipt identity.
    kind: Operation kind; Until results carry a validated report.
    status: Whether the operation was observed, rejected, or left unknown.
    result: Operation-specific result payload, or None.
    observation: Optional browser evidence attached to the operation.
    error: Optional retained error detail.

[Source: python/yosoi/browser.py:897](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L897-L933)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: StrictStr
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

[Source: python/yosoi/browser.py:929](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L929-L933)
