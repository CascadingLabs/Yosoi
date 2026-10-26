---
title: "NodeValue"
description: "yosoi.outcomes.NodeValue Python API reference."
order: 0
---

`yosoi.outcomes.NodeValue`

```python
class NodeValue(ImmutableModel):
```

Tagged document-bound node reference rather than a content copy.

Attributes:
    kind: Discriminator fixed to node for tagged decoding.
    value: Document identity and native coordinate; retain the document to interpret
        it.

[Source: python/yosoi/outcomes.py:666](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/outcomes.py#L666-L676)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['node']
value: NodeReference
```
