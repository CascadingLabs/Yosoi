---
title: "ArchivedContractOutcome"
description: "yosoi.contracts.ArchivedContractOutcome Python API reference."
order: 0
---

`yosoi.contracts.ArchivedContractOutcome`

```python
ArchivedContractOutcome = _runtime_contracts.ArchivedContractOutcome
```

Inspect a portable Contract outcome without a live Rust handle.

Parsing verifies the archive structure; it does not re-execute extraction or prove
business success. The original JSON is retained unchanged.

Attributes:
    view: Immutable status-tagged DTO parsed from the supplied archive JSON.

[Source: python/yosoi/contracts.py:992](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L992-L992)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-outcome/)

[Source: python/yosoi/runtime_contracts.py:437](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L437-L529)
