---
title: "BrowserLimits"
description: "yosoi.policy.BrowserLimits Python API reference."
order: 0
---

`yosoi.policy.BrowserLimits`

```python
class BrowserLimits(Model):
```

Browser evidence byte bounds and capture resource counts.

Attributes:
    dom_utf8_bytes: Maximum retained rendered-DOM UTF-8 bytes.
    ax_json_utf8_bytes: Maximum retained accessibility-tree JSON UTF-8 bytes.
    max_events: Positive addressable browser-event count.
    max_resources: Positive addressable resource count admitted to one capture.
    max_accessibility_nodes: Positive addressable node count in an accessibility
        response.

[Source: python/yosoi/policy.py:329](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L329-L351)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
dom_utf8_bytes: AddressableByteLimitValue = _field('request', 'browser', 'dom_utf8_bytes')
ax_json_utf8_bytes: AddressableByteLimitValue = _field('request', 'browser', 'ax_json_utf8_bytes')
max_events: EventLimitValue = _field('request', 'browser', 'max_events')
max_resources: ResourceLimitValue = _field('request', 'browser', 'max_resources')
max_accessibility_nodes: AccessibilityNodeLimitValue = _field('request', 'browser', 'max_accessibility_nodes')
```
