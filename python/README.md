# Yosoi Python SDK

Yosoi's Python package provides Pydantic authoring and typed outcomes over the
public Rust SDK. The surface includes browser Flows and owned Session/Work
contexts, documents, locator plans, typed Contracts, policy, asynchronous
Requests, Map, Search, and caller-controlled cancellation. Rust parses and
locates documents, groups raw Contract evidence, acquires URLs, discovers
candidates, and validates Policy. Python Contracts construct and validate
their records through Pydantic. Cross-language parity is tracked per public
item; this package does not claim complete verified parity.

Pydantic models describe inputs and result values. The packaged PyO3 extension
calls the public Rust SDK for native processing. Python Contract fields use
ordinary Pydantic types, defaults, aliases, constraints, validators, and
serializers. Python objects also hold native handles; for example, a parsed
document can be reused and closed explicitly or with a context manager.
Pydantic 2 is the only declared Python runtime dependency; the native
extension is part of the package.

> [!NOTE]
> **Python**
>
> A typed `Contract` record follows its Pydantic model behavior. Its native
> schema identity covers only the transport shape. `RuntimeContract` is the
> separate API for Rust-owned String and Money conversion, validation, and
> portable archives.

Start with the [runnable review examples](examples/README.md) to inspect Rust
policy defaults, Contract schemas and evidence, local HTTP workflows, and
network outcomes. The [browser beta example](examples/browser_beta.py) shows
Flows built from caller-supplied site actions, Contract plans, and typed
expectations without embedding site selectors.

## Browser beta API

Build immutable action sequences with `ys.flow([...])`, then call
`await flow.invoke()` for a managed browser or `await flow.invoke(work)` to
borrow an acquired Work lease. `flow.bind(policy).invoke()` applies an explicit
validated Yosoi Policy. `FlowOutcome.require_completed()` returns the original
outcome when every step completes and raises `FlowExecutionError` with that
same outcome for failed, cancelled, unknown, or issue-bearing execution.
Native invocation failures that include partial execution or cleanup details
raise `FlowInvocationError` with those facts attached.

The flow policy retains Rust's `Continue` defaults when `on_failure` and
`on_cancellation` are omitted. That is useful for independent steps; workflows
with dependent side effects should stop after a failed assertion. The flat
`ys.flow(...)` factory accepts explicit timeout, continuation, and failure
capture settings:

~~~python
checkout = ys.flow(
    steps,
    timeout_ms=30_000,
    on_failure=ys.policy.Stop(scope="invocation"),
    on_cancellation=ys.policy.Stop(scope="invocation"),
)
~~~

`ys.session(...)` creates an async context manager that owns the browser
Session. Its `work()` context manager borrows control; Work release does not
close the Session, and leaving the Session context closes it. JavaScript
evaluation needs an explicit managed Flow grant with `.allow_javascript()`;
both `flow.allow_javascript().bind(policy)` and
`flow.bind(policy).allow_javascript()` keep that grant on the managed Flow.
For a borrowed Work lease, grant it through the owning
`SessionPolicy(allow_arbitrary_js=True)` and the allowed action list; a Flow
grant cannot elevate that Session's policy.

`ys.request.new(url).in_session(session).send()` uses the retained Session's
browser request policy. `.with_work(work)` sends on an existing borrowed Work
lease, and `.bind(policy)` keeps an explicit Policy when either owner is
selected. These request wrappers leave Session and Work cleanup with their
caller and return the same typed `Response` with its document outcomes.

`ys.evaluate_file(path)`, `ys.run_module(path)`, and
`ys.run_module_with_export(path, name)` synchronously snapshot and validate
source before invocation. Files are bounded UTF-8 source. Module imports must
form a bounded relative local graph; remote, absolute, bare, and computed
dynamic imports are rejected. Selected exports are read as JSON after
evaluation and are not invoked.

Typed `ys.assert_all(Contract, plan=..., checks=[...])` assembles one immediate
Contract observation, constructs its Python model through Pydantic, and runs
all synchronous predicates against that record. Attach `.until()` or pass the assertion to
`ys.until(...)` when bounded polling is intended. Callback exceptions remain
visible as structured check errors; async predicates and non-boolean results
are rejected. Serialized assertion descriptors contain no Python code, so a
Flow loaded from a persisted descriptor must be rebuilt with its local checks
before invocation.

> [!NOTE]
> **Python**
>
> Pydantic validation runs before assertion predicates. If model construction
> fails, the predicates are skipped and the report retains the candidate and
> structured validation details.

This Python surface does not expose Watch streams, additional tab creation,
or remote browser attachment. The example accepts site-specific actions,
expectations, Plans, and Contracts from the caller; it does not discover or
certify a website automatically.

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
