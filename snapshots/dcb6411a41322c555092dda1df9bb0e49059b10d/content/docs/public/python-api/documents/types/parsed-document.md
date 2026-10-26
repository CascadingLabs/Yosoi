---
title: "ParsedDocument"
description: "yosoi.documents.ParsedDocument Python API reference."
order: 0
---

`yosoi.documents.ParsedDocument`

```python
class ParsedDocument:
```

A reusable Rust parse; close explicitly or use it as a context manager.

[Source: python/yosoi/documents.py:467](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L467-L513)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.ParsedDocument) -> None:
```

Retain a native parse handle without acquiring or reparsing data.

Args:
    handle: Native owner returned by a supported parse operation.

[Source: python/yosoi/documents.py:470](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L470-L476)

### locate

```python
def locate(self, plan: Plan) -> LocateOutcome:
```

Reuse retained parse evidence for an authored locator plan.

Args:
    plan: Outputs and projections to evaluate against the parse.

Returns:
    Typed matches, absence, incomplete evidence, or failure.

Raises:
    ClosedResourceError: The parse has already been closed.

[Source: python/yosoi/documents.py:478](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L478-L490)

### closed

```python
@property
def closed(self) -> bool:
```

Return whether native parse ownership has been explicitly closed.

[Source: python/yosoi/documents.py:493](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L493-L495)

### close

```python
def close(self) -> None:
```

Close native parse ownership; repeated closes are harmless.

[Source: python/yosoi/documents.py:497](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L497-L499)

### __enter__

```python
def __enter__(self) -> Self:
```

Return this parse owner for context-managed use.

Raises:
    ClosedResourceError: The parse was closed before context entry.

[Source: python/yosoi/documents.py:501](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L501-L509)

### __exit__

```python
def __exit__(self, *args: object) -> None:
```

Close native parse ownership on context exit, including on errors.

[Source: python/yosoi/documents.py:511](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/documents.py#L511-L513)
