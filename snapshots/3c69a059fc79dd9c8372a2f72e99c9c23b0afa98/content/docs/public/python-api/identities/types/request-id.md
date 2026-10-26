---
title: "RequestId"
description: "yosoi.identities.RequestId Python API reference."
order: 0
---

`yosoi.identities.RequestId`

```python
class RequestId(ActivityId):
```

A validated activity UUID used to correlate one authored request.

The Python type distinguishes request vocabulary without changing UUID
encoding or checking whether the request has executed.

[Source: python/yosoi/identities.py:96](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/identities.py#L96-L105)

## Base classes

[ActivityId](/yosoi/python-api/identities/types/activity-id/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### activity_id

```python
def activity_id(self) -> ActivityId:
```

Return the same request UUID represented as a general activity identity.

[Source: python/yosoi/identities.py:103](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/identities.py#L103-L105)
