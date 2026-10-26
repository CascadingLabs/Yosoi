---
title: "TextWithCaptures"
description: "yosoi.outcomes.TextWithCaptures Python API reference."
order: 0
---

`yosoi.outcomes.TextWithCaptures`

```python
class TextWithCaptures(ImmutableModel):
```

Tagged text projection with named regular-expression captures.

Attributes:
    kind: Discriminator fixed to text_with_captures for tagged decoding.
    value: Full projected text paired with its named capture values.

[Source: python/yosoi/outcomes.py:593](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L593-L602)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['text_with_captures']
value: CapturedText
```
