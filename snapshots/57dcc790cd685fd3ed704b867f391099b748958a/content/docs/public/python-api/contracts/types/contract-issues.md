---
title: "ContractIssues"
description: "yosoi.contracts.ContractIssues Python API reference."
order: 0
---

`yosoi.contracts.ContractIssues`

```python
class ContractIssues(_native.ContractError):
```

Structured rejection of a request for all accepted record values.

Attributes:
    detail: Copied top-level Rust rejection mapping. Nested values are not
        recursively frozen; the original outcome remains available.

[Source: python/yosoi/contracts.py:414](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L414-L431)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, detail: Mapping[str, Any]) -> None:
```

Copy top-level Rust rejection details and encode an exception message.

Args:
    detail: Rejection counts or terminal classification supplied by Rust.

Nested values are not frozen; the original outcome retains its evidence.

[Source: python/yosoi/contracts.py:422](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L422-L431)
