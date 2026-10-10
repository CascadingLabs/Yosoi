# Release CD

CI and CD have separate entry points. Existing PR/main checks remain in their
CI workflows. `release-cd.yml` runs only for release tag pushes or a manual run
against an existing release tag. Opening this PR does not publish packages.
`release-tooling-ci.yml` checks only the release helpers when their files change;
it runs formatting, lint, and synthetic artifact tests without compiling Rust.

## Release sequence

1. Merge the SDK and CD stack, synchronize the chosen `0.MINOR.PATCH` version
   and citation date with `cargo xtask bump-version`, and finalize the canonical
   release notes. `cargo xtask release check VERSION` must pass.
2. Tag that commit on `main` as `v0.MINOR.PATCH`. A tag push runs release CD;
   a manual dispatch defaults to validation only (`publish: false`). Dispatch
   from the release tag so GitHub's workflow identity also matches the release.
3. CD checks the tag/version/main ancestry, exports one source distribution,
   builds its wheels, tests installed wheels outside the source tree, builds
   and tests native Rust artifacts, and generates matching public docs and
   compiler-backed API reference. Matrix completeness is a hard gate.
4. A separate prerequisite gate runs before any registry upload. Crates publish
   in dependency order, then verified Python distributions publish through PyPI
   Trusted Publishing. Clean binary-only installations from PyPI are tested on
   every platform/interpreter before finalizing a GitHub beta prerelease.
5. GitHub assets include the Python distributions, native CLI archives, versioned
   docs/reference bundle, release plan with source commit, and SHA256SUMS.

Builds use one Cargo worker and one Rayon worker. Each matrix runs one job at a
time. Cargo caches separate CLI, wheel ABI/target, release identity, reference,
and crate packaging. Release builds clear inherited Rust flags and do not use
`target-cpu=native`. Linux wheels are audited against **manylinux 2.28**; Linux
CLI archives use the Ubuntu 24.04 native runner baseline, not manylinux.

| Platform | Rust target | Hosted runner |
| --- | --- | --- |
| Linux x86-64 | x86_64-unknown-linux-gnu | ubuntu-24.04 |
| Linux ARM64 | aarch64-unknown-linux-gnu | ubuntu-24.04-arm |
| Windows x86-64 | x86_64-pc-windows-msvc | windows-2025 |
| macOS Apple Silicon | aarch64-apple-darwin | macos-15 |
| macOS Intel | x86_64-apple-darwin | macos-15-intel |

Interpreter ABIs follow the bounded `requires-python` range. CPython 3.12–3.15,
3.14t, and 3.15t are included at this stack base. Each ABI/platform gets
a separate wheel. macOS has separate Intel/Apple Silicon wheels with a macOS
11.0 minimum. Windows ARM64, universal macOS wheels, and musllinux are deferred.

## Required external setup and current blockers

- GitHub repository secret **CARGO_REGISTRY_TOKEN** must authorize the selected
  first-party crates. Credentials are exposed only to the crate upload step.
- PyPI must configure Trusted Publishing for `CascadingLabs/Yosoi`, workflow
  `release-cd.yml`, environment `pypi`. The GitHub environment already exists;
  its existence does not prove the PyPI publisher is configured. No PyPI API
  token is required. OIDC is limited to the PyPI publication job.
- The current Rust browser dependency chain is not registry-publishable:
  `yosoi-web-capture` depends on `void_crawl_core`, marked `publish = false`.
  Its vendored Chromiumoxide/CDP chain also needs an approved distribution
  strategy before registry publication. Optional Cargo dependencies still
  require registry availability. CD fails before **any** upload until these
  prerequisites are resolved; it does not silently remove browser features or
  publish patched upstream packages under upstream names.
- The Python stack's hosted checks must pass before release; its local fixes
  do not establish a passing hosted wheel matrix.
- This PR publishes a versioned docs/reference **bundle**, not a frontend
  deployment. CascadingLabsFE's prepare/export/register contract remains the
  deployment boundary: import this bundle's `reference/`, prepare the same SDK
  commit/version, export and commit immutable HTML artifacts, register their
  committed hashes, then build/deploy the frontend. `DOCS_DEPLOY_TOKEN` is not
  exposed because this workflow does not write to that repository.
- Artifact installation checks do not certify browser execution. Windows/macOS
  browser support needs platform-specific certification before advertising it;
  the current browser executable eligibility policy is Linux-specific.

## Retry and verification behavior

Publication is serialized per release tag and is never cancelled midway by a
new run. A retry verifies an existing crates.io package or PyPI filename against
the locally built SHA-256 before skipping it. Different bytes fail and require
a new release version; there is no `skip-existing` bypass. Rebuilt artifacts
may differ, in which case the safe outcome is failure rather than replacement.
GitHub uploads never use `--clobber`, verify existing asset bytes, and refuse to
add files to a release that is already published. Publication across registries
is sequential rather than atomic; a failed run may leave preceding uploads.
Rerun after resolving the failure, retaining the exact tag/source identity.

Focused local verification does not build native wheels or contact registries:

```sh
uv run --locked --project scripts/releases python -m unittest discover -s scripts/cd/tests
uv run --locked --project scripts/releases python scripts/cd/release.py publication-ready --tag v0.1.0
```

The second command currently fails with the named browser dependency blocker.
The complete hosted build/install/test matrix runs during release CD, never as
an additional full matrix on every PR.
