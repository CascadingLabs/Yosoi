---
title: 'Install'
description: 'Install Yosoi in a Rust or Python project.'
order: 1
---

# Install

## Requirements

Rust projects need Rust 1.99 or newer. Python projects need Python 3.12 through 3.15. The Python package includes its native extension and depends on Pydantic.

> Yosoi supports free-threaded builds in python 3.14 and 3.15

Yosoi is published on [crates.io](https://crates.io/crates/yosoi) and [PyPI](https://pypi.org/project/yosoi/). Python wheels vary by operating system, architecture and interpreter ABI.

## Install

### Cargo

```sh
cargo add yosoi
```

### UV

```sh
uv add yosoi
```

## Next steps

Read [Concepts](../concepts/index.md), send a [Request](../sdk/requests.md), or produce a typed record with [Contracts](../sdk/contracts.md).

For shell workflows, install the [CLI](../cli/index.md). Browser execution also needs compatible regular Chrome or Chromium; see [Browser](../sdk/browser.md).

For a browser service in a container, see [Docker setup](docker.md).
