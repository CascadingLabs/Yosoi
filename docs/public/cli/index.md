---
title: 'CLI'
description: 'Install the published command-line tool and combine its operations.'
order: 0
---

# CLI

Use the CLI for one-off tasks, saved evidence and shell pipelines.

## Install the CLI

Choose the installer you already use. All four methods provide the `yosoi`
command.

| Method               | Use it on                                         | Installation                                       |
| -------------------- | ------------------------------------------------- | -------------------------------------------------- |
| uv or uvx            | Windows, macOS, Linux                             | [Prebuilt Python tool package](#uv-and-uvx)        |
| Shell installer      | Linux, macOS                                      | [Linux](#linux) or [macOS](#macos) binary download |
| PowerShell installer | Windows x86-64                                    | [Windows binary download](#windows-powershell)     |
| Cargo                | Platforms with Rust and native build dependencies | [Manual source build](#cargo)                      |

### uv and uvx

```sh
uv tool install yosoi-cli
yosoi --help
```

This installs a prebuilt executable. Rust and Cargo are not required. The
`yosoi-cli` package supplies the `yosoi` command; the `yosoi` Python package
supplies the SDK for application code.

For a single command without a permanent tool installation:

```sh
uvx --from yosoi-cli yosoi --help
```

### Linux

```sh
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/CascadingLabs/Yosoi/releases/latest/download/install.sh -o install-yosoi.sh
sh install-yosoi.sh
yosoi --help
```

The Linux installer supports x86-64 and ARM64 with glibc 2.39 or newer, such
as Ubuntu 24.04. It downloads the binary for your operating system and CPU, checks
its SHA-256 against the release manifest, and installs it in `~/.local/bin`.
Add that directory to your shell's PATH if the installer asks you to.
You can inspect the downloaded script before running it.

### macOS

```sh
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/CascadingLabs/Yosoi/releases/latest/download/install.sh -o install-yosoi.sh
sh install-yosoi.sh
yosoi --help
```

The macOS installer supports Apple Silicon and Intel Macs on macOS 11.0 or
newer. It selects your CPU architecture, verifies the download and installs
the executable in `~/.local/bin`. Add that directory to your shell's PATH
if the installer asks you to. Rust, Cargo and Python are not required.

### Windows PowerShell

```powershell
Invoke-WebRequest https://github.com/CascadingLabs/Yosoi/releases/latest/download/install.ps1 -OutFile install-yosoi.ps1
& ./install-yosoi.ps1
yosoi --help
```

The installer verifies and installs the Windows x86-64 executable in
`$env:LOCALAPPDATA\Yosoi\bin`. It adds that directory to your user PATH and
the current PowerShell session. Open a new terminal to refresh other sessions.
If your PowerShell execution policy blocks downloaded scripts, review the
script and use `Unblock-File ./install-yosoi.ps1` where your policy permits it.

### Cargo

```sh
CARGO_BUILD_JOBS=1 cargo install yosoi --features cli --bin yosoi --locked
yosoi --help
```

This builds the published [yosoi crate](https://crates.io/crates/yosoi). It needs Rust 1.99 or newer and native build prerequisites for your platform. The `cli` feature includes browser support but does not install Chrome or Chromium.

All installation methods run the same CLI. Prebuilt Linux releases require
glibc 2.39 or newer, such as Ubuntu 24.04, and macOS releases require 11.0 or
newer. Linux and macOS support x86-64 and ARM64; Windows supports x86-64.
Older Linux and musl systems can use the manual Cargo path with the required
native build dependencies. Browser operations require a separately installed,
supported regular Chrome or Chromium Stable.

## Versions, upgrades and removal

Pin a version with `uv tool install yosoi-cli==0.2.1`,
`sh install-yosoi.sh --version 0.2.1`, or
`& ./install-yosoi.ps1 -Version 0.2.1`. Custom destinations use
`--install-dir /absolute/path` or `-InstallDir C:\absolute\path`.
`YOSOI_VERSION` and `YOSOI_INSTALL_DIR` provide the same installer defaults.

For a uv installation, upgrade with `uv tool upgrade yosoi-cli` and remove it
with `uv tool uninstall yosoi-cli`. For a script installation, rerun that script
to upgrade; remove the installed executable to uninstall. On Windows, also
remove the Yosoi directory from your user PATH if you no longer use it.
Cargo installations use `cargo install yosoi --features cli --bin yosoi --locked`
to upgrade and `cargo uninstall yosoi` to remove the executable.

If `uv tool list` shows an old `yosoi` tool with version `0.0.3a26`, remove it
with `uv tool uninstall yosoi` before installing `yosoi-cli`. Avoid installing
the CLI through multiple methods at once. Run `yosoi --version` to check which
version your shell selected.

## Commands

| Command                       | Task                        |
| ----------------------------- | --------------------------- |
| [`yosoi request`](request.md) | Acquire a document          |
| [`yosoi locate`](locate.md)   | Select values from evidence |
| [`yosoi map`](map.md)         | Inventory a site            |
| [`yosoi search`](search.md)   | Find provider candidates    |

## Fetch and locate

```sh
yosoi request https://example.org/ --raw > page.html
```

`--raw` emits document bytes. For a typed pipeline, retain default document output:

```sh
set -o pipefail
yosoi request https://example.org/ --pipe-document | yosoi locate --pipe-document --css 'h1' --json
```

The selector is a concrete query for this demonstration page. Other sites need queries or bindings that match their evidence.

## Configuration and completions

Use [Policy profiles](policy.md) to inspect the choices used by an operation. Generate shell completions from the command tree:

```sh
yosoi completions bash > yosoi-completions.bash
```

## Read the result

Use `--json` for ordinary JSON, `--raw` for bytes, and typed document pipes to connect Request with Locate. Keep unsuccessful outcomes visible. `pipefail` makes an unsuccessful upstream command fail the pipeline.

Use each command's `--help` for its full options. Continue with [SDK](../sdk/index.md) for application integration.
