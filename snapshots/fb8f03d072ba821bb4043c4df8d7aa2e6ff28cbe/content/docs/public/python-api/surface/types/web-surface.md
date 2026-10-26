---
title: "WebSurface"
description: "yosoi.surface.WebSurface Python API reference."
order: 0
---

`yosoi.surface.WebSurface`

```python
class WebSurface:
```

Shared read protocol over an immutable HTML or rendered-DOM index.

Args:
    index: Prepared document index; other document classes are rejected.
    source: Nonempty continuing-source identity, without browser authority.

[Source: python/yosoi/surface.py:585](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L585-L626)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, index: Surface, source: str) -> None:
```

Bind a web observation to its source; no browser is opened.

[Source: python/yosoi/surface.py:593](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L593-L595)

### descriptor

```python
@property
def descriptor(self) -> Descriptor:
```

Return read capabilities; this immutable adapter is not controllable.

[Source: python/yosoi/surface.py:598](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L598-L600)

### observation

```python
@property
def observation(self) -> Observation:
```

Return the exact source-bound interpretation identity.

[Source: python/yosoi/surface.py:603](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L603-L605)

### root_reference

```python
@property
def root_reference(self) -> Reference:
```

Return the full web observation's shared address.

[Source: python/yosoi/surface.py:608](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L608-L610)

### read

```python
def read(self, request: ReadRequest) -> ReadResult:
```

Read in Rust; the complete tagged result fits the requested byte budget.

[Source: python/yosoi/surface.py:612](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L612-L614)

### reference

```python
def reference(self, reference: NativeReference) -> Reference:
```

Convert an exact index reference into this source-bound shared address.

[Source: python/yosoi/surface.py:616](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L616-L620)

### native_reference

```python
def native_reference(self, reference: Reference) -> NativeReference:
```

Recover an index reference; foreign observations are rejected by Rust.

[Source: python/yosoi/surface.py:622](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L622-L626)
