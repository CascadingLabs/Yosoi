# Python SDK compatibility verification

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
