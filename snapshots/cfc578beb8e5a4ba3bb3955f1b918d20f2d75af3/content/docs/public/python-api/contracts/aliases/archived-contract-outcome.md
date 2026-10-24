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

[Source: python/yosoi/contracts.py:1626](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L1626-L1626)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-outcome/)

[Source: python/yosoi/runtime_contracts.py:437](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L437-L529)
