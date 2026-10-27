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

[Source: python/yosoi/contracts.py:430](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L430-L447)

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

[Source: python/yosoi/contracts.py:438](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L438-L447)
