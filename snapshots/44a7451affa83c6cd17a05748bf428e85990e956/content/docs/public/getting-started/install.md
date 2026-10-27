---
title: 'Install'
description: 'Install Yosoi in a Rust or Python project.'
order: 1
---

# Install

## Requirements

Rust projects need Rust 1.99 or newer. Python projects need Python 3.12 through 3.15. The Python package includes its native extension and depends on Pydantic.

Free-threaded Python 3.14 and 3.15 builds are supported.

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

The Surface and optional-browser guides require Yosoi 0.4.0 or newer. See the [0.4.0 release notes](../releases/0-4-0.md) for version-specific commands and breaking changes when upgrading from 0.3.0.

Read [Concepts](../concepts/index.md), send a [Request](../sdk/requests.md), or produce a typed record with [Contracts](../sdk/contracts.md).

For shell workflows, install the [CLI](../cli/index.md). The default browser engine needs compatible regular Chrome or Chromium; see [Browser](../sdk/browser.md). [Choosing a browser](../concepts/choosing-a-browser.md) covers optional Firefox and Moli support.

For a browser service in a container, see [Docker setup](docker.md).
