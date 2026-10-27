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

[Source: python/yosoi/contracts.py:1565](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L1565-L1565)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-outcome/)

[Source: python/yosoi/runtime_contracts.py:405](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L405-L497)
