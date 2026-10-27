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

[Source: python/yosoi/identities.py:96](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/identities.py#L96-L105)

## Base classes

[ActivityId](/yosoi/python-api/identities/types/activity-id/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### activity_id

```python
def activity_id(self) -> ActivityId:
```

Return the same request UUID represented as a general activity identity.

[Source: python/yosoi/identities.py:103](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/identities.py#L103-L105)
