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
    detail: Copied terminal, cardinality, or report-level rejection facts. Nested
        values are not recursively frozen; the extraction report remains available.

[Source: python/yosoi/contracts.py:480](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L480-L497)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, detail: Mapping[str, Any]) -> None:
```

Copy top-level Rust rejection details and encode an exception message.

Args:
    detail: Safe rejection counts, validation details, or terminal facts.

Nested values are not frozen; the original outcome retains its evidence.

[Source: python/yosoi/contracts.py:488](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L488-L497)
