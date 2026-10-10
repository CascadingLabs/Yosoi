# Python SDK compatibility verification

## Python 3.15 verification

Verified locally on Linux x86-64 on 2026-10-09, extending the SDK-completion
revision `4c45cc76412351d1c438d309b683bbc0a453a86c`. The declared interpreter
range is now `>=3.12,<3.16`, with Pydantic `>=2.14,<3`.

| Interpreter | Installed wheel ABI | SDK tests | Review commands |
| --- | --- | --- | --- |
| CPython 3.15.0 | `cp315` | 282 passed, one free-threading-only skip | 6 passed |
| CPython 3.15.0 free-threaded | `cp315t` | 283 passed | 6 passed |

Both development-profile wheels are built from the same source distribution
with the Rust browser feature enabled and installed before testing. Tests run
with isolated Python (`-I`). Pydantic 2.14.0 and pydantic-core 2.50.0 are used
on both interpreters. The six review commands are `policy`, `locate`,
`contracts`, `runtime-contracts`, `errors`, and `local`.

The free-threading test starts a fresh interpreter without `PYTHON_GIL=0`,
treats warnings as errors, and checks imports, concurrent parsing, shared
parsed-document access, and Contract validation. The GIL remains disabled.
Builds pass the resolved interpreter path to Maturin so a shared Cargo target
cannot reuse the normal interpreter's extension for the free-threaded ABI.

Build, test, review, and interpreter logs are retained in
`.generated/python315/` in the Python 3.15 workspace. Wheels use native
`linux_x86_64` platform tags and are local validation artifacts. Hosted CI,
other platforms, browser execution, and release publication are not established
by these checks. Earlier interpreter results below predate the Pydantic upgrade.

## Current integrated SDK evidence

The SDK continuation is based on the updated default workspace revision
`c26eace7b2dc746fcde1072748ff6cc6c7fe2114`. On 2026-10-05 (local time),
separate development-profile wheels built from the current workspace passed
the installed-package checks on Linux x86-64:

| Interpreter | Wheel ABI | Latest installed SDK tests |
| --- | --- | --- |
| CPython 3.12.14 (current workspace) | `cp312` | 282 passed, 1 free-threading-only skip |
| CPython 3.13.1 (current workspace) | `cp313` | 282 passed, 1 free-threading-only skip |
| CPython 3.14.8 (current workspace) | `cp314` | 282 passed, 1 free-threading-only skip |
| CPython 3.14.8 free-threaded (current workspace) | `cp314t` | 283 passed |

Tests ran with isolated Python (`-I`) against installed wheels. The
free-threading test uses a fresh interpreter without forcing `PYTHON_GIL=0`;
Yosoi/Pydantic imports, concurrent parsing, and Contract validation leave the
GIL disabled. The wheels enable the Rust browser feature; browser execution
was not certified by these checks.

The current source distribution also passes that same four-interpreter matrix.
Its SHA-256 is
`54126186b9ae56c4116ff060db2f00723738dc1b8321c03a060d7e8e8ccd0d2d`.
The Python payloads in every wheel match both the extracted archive and the
workspace package. Offline Cargo normalization removes 53 unused packages and
changes no retained package versions, checksums, or dependency records.

Reproducible local evidence is stored in `.local/current-sdk-sdist/identity.json`,
`packaging-proof.json`, `test-suite-manifest.json`, and `tests-INTERPRETER.log`.
The supported platform evidence is Linux x86-64, with development-profile
`manylinux_2_39_x86_64` wheels. Hosted CI and browser certification are separate
from these local checks. The semantic SDK parity gate and supported-ABI matrix
are configured in `.github/workflows/python-ci.yml`.

## Historical scaffold evidence

Verified locally on Linux x86-64 on 2026-10-04. The declared range is
`>=3.12,<3.15`; the CI matrix selects normal 3.12, 3.13, 3.14 and exact 3.14.3t.

| Interpreter actually used | Wheel built from the sdist | SDK tests | Review commands |
| --- | --- | --- | --- |
| 3.12.14 | `yosoi-0.1.0-cp312-cp312-manylinux_2_38_x86_64.whl` | 25 passed, 1 skipped | 7 passed |
| 3.13.1 | `yosoi-0.1.0-cp313-cp313-manylinux_2_38_x86_64.whl` | 25 passed, 1 skipped | 7 passed |
| 3.14.3 | `yosoi-0.1.0-cp314-cp314-manylinux_2_38_x86_64.whl` | 25 passed, 1 skipped | 7 passed |
| 3.14.3 free-threaded | `yosoi-0.1.0-cp314-cp314t-manylinux_2_38_x86_64.whl` | 26 passed | 7 passed |

Each wheel was built in the development profile from the same extracted source
distribution, then installed into a separate environment. Tests and examples
ran outside the Python source directory, without `PYTHONPATH`, against the
installed package. Normal builds skip the free-threading-only test. That test
passes on exact 3.14.3t without forcing `PYTHON_GIL=0`.

The 28 review runs cover `policy`, `locate`, `local`, `request`, `map`, `search`,
and `cancel` on every interpreter. The local example uses real loopback HTTP.
Public Requests received HTTP 200 from example.org; Bing returned five results
on each interpreter. All seven 3.14.3t examples reported the GIL disabled after
SDK operations. These observations do not certify a Search provider.

Tests cover policy defaults/identity/snapshotting, direct and reused parses,
source ownership after Python object deletion, concurrent parsed access,
request/map capture retention, Rust cleanup after Python task cancellation,
sibling cancellation isolation, and native-handle reconstruction for Pydantic
request copies. Lint and type checks target Python 3.12 syntax.

Pydantic 2.13.5 and pydantic-core 2.46.5 were used in all four environments.
Python runtime dependencies remain Pydantic and the packaged native extension.

## Limits

This is local development-profile evidence, not hosted CI or published release
artifacts. The local wheels target manylinux 2.38 x86-64. macOS, Windows, other
architectures, and lower Linux libc baselines are not established by these runs.
The browser feature was not enabled. Python Contracts authoring and full Rust/
Python API parity remain separate open implementation work.

All six Rust review commands also completed. The authored Python documentation
snippets ran on all four installed-wheel environments. The required public docs
gate passed formatting, 15-page link/navigation/render validation, and 13 tests
with one worker. Its temporary test cache used a workspace-owned directory
after `/tmp` cache creation failed.

See [the example commands](examples/README.md) and [the package workflow](README.md).
Raw local build/test/example logs and interpreter identities are retained under
`.local/compatibility/` in the review workspace.
