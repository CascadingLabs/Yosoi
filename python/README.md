# Yosoi Python SDK

Yosoi's Python package provides Pydantic authoring and typed outcomes over the
public Rust SDK. The current Python surface includes documents, locator plans,
typed Contracts, policy, asynchronous Requests, Map, Search, and
caller-controlled cancellation. Python Contracts are bound to the Rust
extraction and validation pipeline. Cross-language parity is tracked per
public item; this package does not claim complete verified parity.

Pydantic models describe inputs and result values. The packaged PyO3 extension
calls the public Rust SDK, which owns parsing, locator compilation and
evaluation, acquisition and discovery, and complete policy validation. Python
objects hold native handles; for example, a parsed document can be reused and
closed explicitly or with a context manager. Pydantic 2 is the only declared
Python runtime dependency; the native extension is part of the package.

Start with the [runnable review examples](examples/README.md) to inspect Rust
policy defaults, Contract schemas and evidence, local HTTP workflows, and
network outcomes.

The [earlier compatibility report](COMPATIBILITY.md) records a local wheel
matrix for the pre-Contract SDK snapshot. It does not verify the current
Contract binding, CPython 3.14.8t, browser execution, all release platforms, or
live Search providers. The public
[compatibility page](../docs/public/python/compatibility.md) records the
current evidence boundary.

## Interpreter targets and wheels

The package declares `>=3.12,<3.16` and requires Pydantic `>=2.14,<3`.
Its interpreter targets are normal CPython 3.12–3.15, plus free-threaded
CPython 3.14.8t and 3.15.0t.

The native extension uses interpreter-specific wheels: `cp312`, `cp313`,
`cp314`, `cp314t`, `cp315`, and `cp315t`. These ABI tags do not promise a wheel for every
operating system or architecture. Check the artifacts for the release and
platform you plan to install.

Python CI is configured for all six targets. For each target it builds a wheel
from an sdist, installs that wheel, runs package checks, and requests the
`policy`, `locate`, `contracts`, and `local` examples. Workflow configuration
is not evidence of a completed hosted run or of published wheels for all
platforms. Local Search examples do not certify live providers.

## Local workflow

Install one selected interpreter and the locked development environment from
the repository root. Substitute `3.13`, `3.14`, or the exact
`3.14.8t`, `3.15.0`, or `3.15.0t` selector to work with another target:

~~~sh
uv python install 3.12 3.13 3.14 3.14.8t 3.15.0 3.15.0t
uv sync --locked --python 3.12
~~~

For package checks that build and install a wheel from an sdist:

~~~sh
uv sync --locked --no-install-project --python 3.12
uv run --no-sync ruff check python
uv run --no-sync ruff format --check python
uv run --no-sync ty check python
interpreter=$(uv run --no-sync python -c 'import os, sys; print(os.path.realpath(sys.executable))')
CARGO_BUILD_JOBS=1 uv build --no-build-isolation --config-setting="build-args=--interpreter=$interpreter"
uv pip install --python .venv/bin/python --reinstall dist/*.whl
uv run --no-sync pytest
~~~

The build command produces an sdist and builds the wheel from it with the locked
development tools. Source builds need the Rust toolchain and native build
prerequisites. Use one Cargo worker. For iterative binding work,
`uv sync --locked --python <interpreter>` builds an editable installation.
The explicit resolved interpreter path keeps the normal and free-threaded
ABIs distinct when switching the project environment with a shared Cargo
target directory.
