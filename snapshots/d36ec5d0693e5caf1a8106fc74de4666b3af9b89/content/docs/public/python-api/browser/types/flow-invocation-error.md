---
title: "FlowInvocationError"
description: "yosoi.browser.FlowInvocationError Python API reference."
order: 0
---

`yosoi.browser.FlowInvocationError`

```python
class FlowInvocationError(BrowserError):
```

Retain native invocation failure and any partial execution evidence.

Attributes:
    native_error: Original native exception.
    outcome: Parsed partial Flow outcome when available.
    outcome_json: Original partial outcome JSON when available.
    outcome_encoding_error: Native failure to encode partial outcome evidence, if
        any.
    cleanup_error: Native cleanup error detail, if any.
    rust_variant: Native failure variant name, if provided.
    outcome_parse_error: Exception encountered while parsing retained partial
        outcome JSON.

[Source: python/yosoi/browser.py:1277](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1277-L1321)

## Base classes

[BrowserError](/yosoi/python-api/browser/aliases/browser-error/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, native_error: BaseException, *, outcome: FlowOutcome | None, outcome_json: str | None, outcome_encoding_error: str | None, cleanup_error: str | None, rust_variant: str | None, outcome_parse_error: BaseException | None=None) -> None:
```

Retain the original native failure and available partial evidence.

Args:
    native_error: Exception from native invocation.
    outcome: Parsed partial outcome, or None when absent or unparseable.
    outcome_json: Original partial JSON, if emitted.
    outcome_encoding_error: Failure to encode an outcome, if reported.
    cleanup_error: Native cleanup failure detail, if reported.
    rust_variant: Rust failure variant name, if reported.
    outcome_parse_error: Error encountered while parsing retained outcome JSON.

[Source: python/yosoi/browser.py:1292](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1292-L1321)
