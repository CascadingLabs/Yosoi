---
title: "DecodedTextLocation"
description: "yosoi.outcomes.DecodedTextLocation Python API reference."
order: 0
---

`yosoi.outcomes.DecodedTextLocation`

```python
class DecodedTextLocation(ImmutableModel):
```

Tagged byte and Unicode-scalar evidence for a decoded-text match.

Attributes:
    kind: Discriminator fixed to decoded_text for tagged decoding.
    coordinate: Paired ranges supplied for the same retained match.

[Source: python/yosoi/outcomes.py:453](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L453-L462)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['decoded_text']
coordinate: DecodedTextCoordinate
```
