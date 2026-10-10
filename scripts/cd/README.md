# Release CD

CI and CD have separate entry points. Existing PR/main checks remain in their
CI workflows. `release-cd.yml` runs only for release tag pushes or a manual run
against an existing release tag. Opening this PR does not publish packages.
`release-tooling-ci.yml` checks only the release helpers when their files change;
it runs formatting, lint, and synthetic artifact tests without compiling Rust.

## Release sequence

Numbered release candidates use Cargo version `0.MINOR.PATCH-rc.N`, tag
`v0.MINOR.PATCH-rc.N`, and Python package version `0.MINOR.PATCHrcN` (PEP 440).
Use `cargo xtask bump-version VERSION --date-released YYYY-MM-DD -y` for the
RC, prepare and finalize its canonical preview notes, merge onto main, and
tag that exact commit. Candidates publish verified GitHub artifacts and the
matching docs bundle after the complete build and installed-artifact matrix
passes. Registry uploads and registry-installed tests run only for final beta
tags. A later final release uses a separate `0.MINOR.PATCH` version and tag;
registry prerequisites and clean published installs remain mandatory for it.
A passing RC build alone does not clear the browser registry blocker.
Standalone main/manual docs runs defer RC publication; only Release CD's verified
`release-docs` bundle with explicit source and version can publish candidate docs.

Maturin reduces the Cargo workspace when exporting the Python sdist. Before
uploading that one shared sdist, CD reconciles its lockfile offline and verifies
that every retained package identity/checksum was already locked in the source.
Cargo metadata must then pass with `--locked`; wheel builds keep that flag.
The archive retains its source payload and uses canonical ownership/timestamps.

1. Merge the SDK and CD stack, synchronize the chosen `0.MINOR.PATCH` version
   and citation date with `cargo xtask bump-version`, and finalize the canonical
   release notes. `cargo xtask release check VERSION` must pass.
2. Tag that commit on `main` as `v0.MINOR.PATCH`. A tag push runs release CD;
   a manual dispatch defaults to validation only (`publish: false`). Dispatch
   from the release tag, or from `main` while it is exactly the tagged commit.
   Publication checks `github.workflow_sha` against the tag's source commit;
   validation-only dispatches may use a different workflow revision.
3. CD checks the tag/version/main ancestry, exports one source distribution,
   builds its wheels, tests installed wheels outside the source tree, builds
   and tests native Rust artifacts, and generates matching public docs and
   compiler-backed API reference. Matrix completeness is a hard gate.
   It also requires successful main Rust and Python CI for the exact tagged
   source commit, awaiting existing runs when needed. Tags do not launch a
   second identical CI suite; a newer failed run cannot reuse an older success.
4. A separate prerequisite gate runs before any registry upload. Crates publish
   in dependency order, then verified Python distributions publish through PyPI
   Trusted Publishing. Clean binary-only installations from PyPI are tested on
   every platform/interpreter before finalizing a GitHub beta prerelease.
5. GitHub assets include the Python distributions, native CLI archives, versioned
   docs/reference bundle, release plan with source commit, and SHA256SUMS.

Hosted Linux/Windows and Intel macOS builds use two Cargo workers; Apple Silicon
uses one. Rayon and local workstation checks remain at one worker. Independent hosted runners
build wheel batches on five platforms and five native artifacts concurrently;
clean published
installation checks run up to ten at a time. Cargo caches include workspace
crates and separate CLI, wheel target, release identity, reference,
and crate packaging. Pinned `sccache` caches compiler results in ordinary Rust
CI and native release builds as well as Maturin wheel builds. Content-keyed
results avoid recompiling unchanged libraries when checkout timestamps change;
compiler, features, flags, and interpreter bindings remain distinct cache inputs.
Cache statistics are emitted by the action. Tests and linking still execute.
Release builds clear inherited Rust flags and do not use `target-cpu=native`.
Linux wheels are audited against **manylinux 2.28**; Linux
CLI archives use the Ubuntu 24.04 native runner baseline, not manylinux.

| Platform | Rust target | Hosted runner |
| --- | --- | --- |
| Linux x86-64 | x86_64-unknown-linux-gnu | ubuntu-24.04 |
| Linux ARM64 | aarch64-unknown-linux-gnu | ubuntu-24.04-arm |
| Windows x86-64 | x86_64-pc-windows-msvc | windows-2025 |
| macOS Apple Silicon | aarch64-apple-darwin | macos-15 |
| macOS Intel | x86_64-apple-darwin | macos-15-intel |

Interpreter tests follow the bounded `requires-python` range: CPython 3.12–3.15,
3.14t, and 3.15t. Each platform builds three wheel types: `cp312-abi3` for ordinary
Python, version-specific `cp314-cp314t`, and `cp315-abi3.abi3t` for Python 3.15's
stable threading ABI. Build features are explicit; the development defaults
remain unchanged. The 15 wheels are built in five platform jobs, sharing a target
directory across three ABI-specific Maturin invocations. Separate feature
selections preserve the correct stable-ABI tags. These batches feed 30
installed-wheel test jobs, so every
supported interpreter still runs the entire Python suite. Free-threaded jobs
verify that importing the extension leaves the GIL disabled. macOS has separate
Intel/Apple Silicon wheels with a macOS
11.0 minimum. Windows ARM64, universal macOS wheels, and musllinux are deferred.

## Performance targets

Warm-cache targets are under 10 minutes for PR CI and under 30 minutes for release
CD. Measure the complete workflow, including queue/setup/cache time, rather than
compiler time alone. Cold first builds are reported separately. All-feature doctests run on a separate
hosted runner alongside the complete coverage suite, and the Rust result gate
requires both. Doctests restore the check job's ordinary all-feature target cache
without overwriting it; compiler-result caches still validate content and flags.

Python CI builds three development-profile wheels from their source distributions
and tests those artifacts on all six interpreters; optimized wheels remain a CD
gate. CI sets a persistent target directory so temporary sdist extraction does
not discard compilation results. Main/tag compiled caches use fresh immutable
save keys with the existing compiler/configuration restore prefix. PRs consume
main's caches without creating duplicate archives that main cannot restore.
Compiler-result caching is also read-only on PRs and non-default validation
branches; main/tag runs populate it.
The per-run key marker is a comment-only nested config file outside crate
ancestor paths, hashed by rust-cache and never loaded by Cargo.

GitHub caches are scoped to refs: different release tags cannot directly consume
one another's caches, but can restore default-branch caches. For publication that
also warms caches for later releases, dispatch `release-cd.yml` from `main` with
`tag: vVERSION` and `publish: true` while main equals that tag's source commit.
If replacing an automatically started tag run, cancel it and confirm it is
terminal before starting the default-branch run. This changes the controller ref,
not the immutable source tag or any verification/publication gates. See
[GitHub cache access rules](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache).

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
- After the GitHub SDK release succeeds, `docs-publish.yml` publishes the exact
  already-built docs/reference bundle to the `docs-artifacts` branch, updates
  its latest catalog, and dispatches `yosoi-docs-published` to CascadingLabsFE.
  Docs/API changes on main can also publish a fresh docs snapshot without a new
  SDK version. The frontend updates a small pointer file; Cloudflare Pages'
  existing Git integration performs the deployment. Only the dispatch step
  uses `DOCS_DEPLOY_TOKEN`, which must authorize repository dispatches to
  CascadingLabsFE. The frontend's own secret of that name must authorize its
  pointer commit. No new Cloudflare token is needed.
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
add files to a release that is already published. Existing drafts with files
outside the expected artifact set are refused; remove those unexpected files
explicitly before retrying. Publication across registries is sequential rather
than atomic; a failed run may leave preceding uploads.
Rerun after resolving the failure, retaining the exact tag/source identity.

Focused local verification does not build native wheels or contact registries:

```sh
uv run --locked --project scripts/releases python -m unittest discover -s scripts/cd/tests
uv run --locked --project scripts/releases python scripts/cd/release.py publication-ready --tag v0.1.0
```

The second command currently fails with the named browser dependency blocker.
The complete hosted build/install/test matrix runs during release CD, never as
an additional full matrix on every PR.


## Reusing compiled test binaries

Compiler-result caches cannot reuse linked test executables. The common Rust
setup pairs a content-hash/timestamp snapshot with its compiled target cache.
After restore, only unchanged tracked regular files with matching modes get
those recorded timestamps; changed, new, environment, and symlinked files do
not. Cargo still checks manifests, compiler/feature flags, dependency changes,
and generated inputs normally. A post step verifies that tracked inputs stayed
unchanged during the job before saving a new paired snapshot. Source mutation
invalidates the snapshot and falls back to ordinary Cargo freshness checks.

This adds a directory to the cache archive, so its first run seeds a new cache
format. Timing targets must be measured on a subsequent warm run. The small
Cargo fixture checks that unchanged code reuses its binary and edited code
really compiles and changes the executable output; the full Rust suites remain
mandatory in CI.


Default and all-feature Nextest suites each run in two exhaustive hash
partitions on separate hosted runners. Each runner still executes one test at a
time; isolated Xvfb displays and processes avoid sharing browser focus or memory
budgets. Both partitions compile the same suite and only partition 1 updates
its target cache. The final Rust gate requires all four test jobs, doctests,
checks, and a combined LCOV/HTML report built from both coverage partitions.
No test selector or ignore rule is narrowed.
