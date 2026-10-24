---
title: 'Installation'
description: 'Add the released Rust or Python SDK and choose capabilities.'
order: 0
---

# Installation

[Install](../getting-started/install.md) runs a first local example. Add Yosoi to your existing project.

## Install

### Cargo

```sh
cargo add yosoi
```

Rust 1.99 or newer is required. Async examples also use Tokio:

```sh
cargo add tokio --features macros,rt
```

### uv

```sh
uv add yosoi
```

Use CPython 3.12 through 3.15. uv resolves the native wheel and Pydantic. Source builds require the Rust toolchain and native prerequisites.

## Browser support

Rust browser examples need the feature:

```sh
cargo add yosoi --features browser
```

Python wheels have a fixed compiled capability set. Extras do not rebuild the extension. Choose the published wheel matching your platform and interpreter ABI.

Both interfaces need compatible regular Chrome or Chromium installed separately for browser work. Keep browser sandboxing and site isolation enabled.

## Packages

The distribution name is `yosoi` on [crates.io](https://crates.io/crates/yosoi/0.2.1) and [PyPI](https://pypi.org/project/yosoi/0.2.1/). The Rust crate name is also `yosoi`.

Continue with [Requests](requests.md), [Documents](documents.md) or [Flows](flows.md).
