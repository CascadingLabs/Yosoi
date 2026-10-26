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

[Source: python/yosoi/surface.py:578](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L578-L619)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, index: Surface, source: str) -> None:
```

Bind a web observation to its source; no browser is opened.

[Source: python/yosoi/surface.py:586](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L586-L588)

### descriptor

```python
@property
def descriptor(self) -> Descriptor:
```

Return read capabilities; this immutable adapter is not controllable.

[Source: python/yosoi/surface.py:591](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L591-L593)

### observation

```python
@property
def observation(self) -> Observation:
```

Return the exact source-bound interpretation identity.

[Source: python/yosoi/surface.py:596](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L596-L598)

### root_reference

```python
@property
def root_reference(self) -> Reference:
```

Return the full web observation's shared address.

[Source: python/yosoi/surface.py:601](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L601-L603)

### read

```python
def read(self, request: ReadRequest) -> ReadResult:
```

Read in Rust; the complete tagged result fits the requested byte budget.

[Source: python/yosoi/surface.py:605](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L605-L607)

### reference

```python
def reference(self, reference: NativeReference) -> Reference:
```

Convert an exact index reference into this source-bound shared address.

[Source: python/yosoi/surface.py:609](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L609-L613)

### native_reference

```python
def native_reference(self, reference: Reference) -> NativeReference:
```

Recover an index reference; foreign observations are rejected by Rust.

[Source: python/yosoi/surface.py:615](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L615-L619)
