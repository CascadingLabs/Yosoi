---
title: "Request"
description: "yosoi.policy.Request Python API reference."
order: 0
---

`yosoi.policy.Request`

```python
class Request(Model):
```

Acquisition deadlines and source/browser evidence budgets.

Attributes:
    maximum_elapsed: Positive total acquisition elapsed budget in microseconds.
    source: Content-coded, representation, and Unicode retention byte bounds.
    browser: DOM/accessibility byte bounds and capture event/resource counts.
    direct_http_redirects: Explicit redirect traversal limits; adapter support is
        checked separately.

[Source: python/yosoi/policy.py:398](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L398-L412)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
maximum_elapsed: MaximumElapsedValue = _field('request', 'maximum_elapsed')
source: SourceLimits = _field('request', 'source')
browser: BrowserLimits = _field('request', 'browser')
direct_http_redirects: Redirects = _field('request', 'direct_http_redirects')
```
