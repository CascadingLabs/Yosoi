# CLI foundation handoff

The first Yosoi CLI slice reads JSON Policy profiles, makes requests, and
locates values in raw or typed Documents. Archive CLI investment is tracked
separately in CAS-511. Run `yosoi --help` for the current command tree.

## Local installation

From the repository root, an isolated Linux development install can be built
with one worker:

```sh
install_root="$(mktemp -d)"
CARGO_BUILD_JOBS=1 cargo install --path crates/yosoi --features cli --bin yosoi \
  --root "$install_root" --debug --offline --locked
"$install_root/bin/yosoi" --version
"$install_root/bin/yosoi" --help
```

For a release-profile local artifact, omit `--debug`:

```sh
release_root="$(mktemp -d)"
CARGO_BUILD_JOBS=1 cargo install --path crates/yosoi --features cli --bin yosoi \
  --root "$release_root" --offline --locked
"$release_root/bin/yosoi" --version
```

Omit `--offline` if the dependencies are not already cached locally.

The recorded `--debug` installation used the separate CLI package at version
0.1.0. It wrote the binary under an isolated root and reported `yosoi 0.1.0`.
That evidence predates the 0.1.1 consolidation into the `yosoi` package and
does not verify the current build. A separate one-worker release-profile
install also succeeded from the locked 0.1.0 source. Its binary completed a localhost
Request-to-Locate typed pipeline, finding source HTML with both processes
returning zero. Hosted CI artifacts and other platforms require separate
certification. An initial locked install warned
that `yoke-derive 0.8.3` was yanked; the certification lockfile now selects
compatible `yoke-derive 0.8.2`, and the repeat locked offline install
succeeded without that warning. The final CLI also resolved an isolated
`XDG_CONFIG_HOME` Policy path and located text in piped HTML from the
installed binary.

## Policy, Request, and Locate

See [CLI Policy profiles](cli-policy-profiles.md) for the version-keyed JSON
file and read-only `path`, `list`, and `validate` commands. Request and Locate
use its active profile by default; `--profile NAME` selects a
different saved profile for one invocation. Request flags apply after that
selection and do not write the file.

```sh
yosoi request https://example.org/ --explain
yosoi request https://example.org/ --json
set -o pipefail
yosoi request https://example.org/ \
  | yosoi locate --css 'h1' --json
```

The command details and output limits are in [Requests CLI](cli-requests.md)
and [Locate CLI and Document pipes](cli-locate.md). The pipeline uses two
processes: pass `--profile NAME` to both sides when both should use that profile.
Structured stdout stays separate from diagnostics on stderr. Ctrl-C asks the
Requests SDK to cancel and reports status 130 after a terminal outcome.

## Shell completions

`yosoi completions SHELL` generates a static script from the current Clap
command tree. Supported values are `bash`, `zsh`, `fish`, `powershell`, and
`elvish`. For example:

```sh
yosoi completions bash > yosoi.bash
yosoi completions zsh > _yosoi
```

The checked-in [completion scripts](../completions) are generated from this
same command tree. A focused process test compares all five files byte for
byte with the generator so command changes cannot leave them stale.

## Validation boundary

Focused CLI process tests exercise Policy selection, a real loopback Request
to Locate OS pipe, typed profile preservation, malformed/oversized frames,
non-2xx and failed/partial Request evidence, distinct Locate outcomes, and
Ctrl-C cancellation. [Focused live CLI QA](cli-live-qa.md) used a verified
regular Chrome Stable 154 executable for Direct HTTP, headless, and headful
Requests on two public URLs, including typed Request-to-Locate pipes. The
complete workspace gate and full browser security/CDP/cleanup/benchmark
certification remain outstanding. The host's older Chromium 152.0.7977.82 is
only a rollback comparison, not release browser evidence. No Chrome for Testing
distribution is supported.

The repository dependency gate passed after replacing the CLI's `directories`
dependency with direct platform config paths; that removed a transitive
MPL-2.0 license rejected by project policy. The repository-wide production
source-size gate failed on twelve existing files outside the CLI package at
that time. Those historical failures are separate from the focused CLI checks
and do not report the current consolidated workspace gate.
