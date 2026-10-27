---
title: "AutomationContext"
description: "yosoi.archive.AutomationContext Python API reference."
order: 0
---

`yosoi.archive.AutomationContext`

```python
class AutomationContext(ImmutableModel):
```

Recorded provenance supplied by the application, without live authority.

Attributes:
    effective_policy_identity: Resolved Policy identity recorded for the run.
    session_policy: Browser settings used by the owner.
    provider: Recorded browser provider label.
    browser_identity: Optional browser identity claimed by the caller.
    source_revision: Optional source revision claimed by the caller.
    parent: Optional immutable parent record reference.

[Source: python/yosoi/archive.py:92](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/archive.py#L92-L109)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
effective_policy_identity: StrictStr
session_policy: SessionPolicy
provider: StrictStr
browser_identity: StrictStr | None = None
source_revision: StrictStr | None = None
parent: AutomationRecordRef | None = None
```
