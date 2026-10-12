---
title: "BoundFlow"
description: "yosoi.browser.BoundFlow Python API reference."
order: 0
---

`yosoi.browser.BoundFlow`

```python
class BoundFlow(ImmutableModel):
```

Retain an immutable Flow with a validated policy snapshot.

The stored wire snapshot is used for invocation. Editing a separate Policy object
does not change this binding.

Attributes:
    flow: Flow declaration to invoke.
    policy: Policy declaration whose serialized snapshot is captured on
        construction.

[Source: python/yosoi/browser.py:800](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L800-L851)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
flow: Flow
policy: Policy
```

## Methods

### model_post_init

```python
def model_post_init(self, context: object) -> None:
```

Capture the validated policy wire snapshot for later invocation.

Args:
    context: Pydantic initialization context; unused by this bridge.

[Source: python/yosoi/browser.py:816](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L816-L823)

### allow_javascript

```python
def allow_javascript(self) -> BoundFlow:
```

Return a managed BoundFlow with JavaScript explicitly enabled.

[Source: python/yosoi/browser.py:825](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L825-L827)

### invoke

```python
async def invoke(self, lease: Work | None=None, *, cancellation: CancellationToken | None=None) -> FlowOutcome:
```

Invoke this Flow with its captured policy and optional borrowed Work.

Args:
    lease: Caller-owned Work, or None for managed acquisition and cleanup.
    cancellation: Optional token bounding execution without rolling back
        effects.

Returns:
    Flow outcome retaining partial, unknown, skipped, and cleanup facts.

Raises:
    BrowserError: Acquisition or execution fails at the native boundary.
    FlowInvocationError: Native failure includes partial or cleanup evidence.

[Source: python/yosoi/browser.py:829](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L829-L851)
