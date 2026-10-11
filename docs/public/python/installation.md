---
title: Install the Python SDK
description: Choose a compatible Yosoi wheel and interpreter ABI.
order: 1
---

# Install the Python SDK

The package requires Python `>=3.12,<3.16` and Pydantic `>=2.14,<3`. Choose
the wheel that matches both your Python ABI and platform:

| Interpreter                | Release wheel selected by the installation checks |
| -------------------------- | ------------------------------------------------- |
| CPython 3.12–3.15          | `cp312-abi3`                                      |
| Free-threaded CPython 3.14 | `cp314-cp314t`                                    |
| Free-threaded CPython 3.15 | `cp315-abi3.abi3t`                                |

The free-threaded ABI has its own extension wheel. The version range alone does
not promise an artifact for every operating system, architecture, or Linux
libc baseline. Check the release files for your target before installing a
prebuilt wheel.

If a compatible release is available from your configured package index,
install it with:

```sh
python -m pip install yosoi
```

For development from this repository, install the locked environment from the
repository root. The example selects normal CPython 3.12; use `3.13`, `3.14`,
`3.15.0`, or the free-threaded `3.14t` or `3.15.0t` selector for another target.

```sh
uv python install 3.12 3.13 3.14 3.14t 3.15.0 3.15.0t
uv sync --locked --python 3.12
```

`uv sync` builds the editable native extension from the checkout. Source builds
need the Rust toolchain and native build prerequisites. To build and install a
wheel locally, follow the package's source-build workflow in
`python/README.md` in the source checkout.

## Browser builds

The native extension can compile Yosoi's `browser` feature. The repository's
Maturin configuration requests that feature when building the Python wheel;
other build commands must enable it explicitly. The feature adds Rust browser
capture support to the extension, but it does not download or bundle Chrome or
Chromium. Install a compatible regular Chrome or Chromium executable
separately. Browser mode is unavailable from a wheel built without the
feature. The installed-wheel browser journeys provide regression evidence for
the [supported beta surface](browser-workflows.md); full browser/controller/CDP
certification remains separate. See [compatibility status](compatibility.md) for
the exact tested sources and environments.
