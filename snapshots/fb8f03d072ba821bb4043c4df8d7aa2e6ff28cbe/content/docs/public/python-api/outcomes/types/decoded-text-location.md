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

[Source: python/yosoi/outcomes.py:453](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/outcomes.py#L453-L462)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['decoded_text']
coordinate: DecodedTextCoordinate
```
