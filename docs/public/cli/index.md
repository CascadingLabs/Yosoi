---
title: 'Install'
description: 'Install the Yosoi command-line tool.'
order: 0
---

# Install

## Install

### Linux

```sh
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/CascadingLabs/Yosoi/releases/latest/download/install.sh -o install-yosoi.sh
sh install-yosoi.sh
```

To install a specific version, pass `--version` to the downloaded script:

```sh
sh install-yosoi.sh --version 0.3.0
```

Supports x86-64 and ARM64 with glibc 2.39 or newer, such as Ubuntu 24.04.
Installs in `~/.local/bin`. Add that directory to your PATH if the installer asks you to.

### UV

```sh
uv tool install yosoi-cli
```

Installs a prebuilt executable. Rust and Cargo are not required.

To install a specific version:

```sh
uv tool install yosoi-cli==0.3.0
```

To run a command without installing the tool permanently:

```sh
uvx --from yosoi-cli yosoi --help
```

### macOS

```sh
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/CascadingLabs/Yosoi/releases/latest/download/install.sh -o install-yosoi.sh
sh install-yosoi.sh
```

To install a specific version, pass `--version` to the downloaded script:

```sh
sh install-yosoi.sh --version 0.3.0
```

Supports Apple Silicon and Intel Macs on macOS 11.0 or newer.
Installs in `~/.local/bin`. Add that directory to your PATH if the installer asks you to.

### Windows

```powershell
Invoke-WebRequest https://github.com/CascadingLabs/Yosoi/releases/latest/download/install.ps1 -OutFile install-yosoi.ps1
& ./install-yosoi.ps1
```

To install a specific version, pass `-Version` to the downloaded script:

```powershell
& ./install-yosoi.ps1 -Version 0.3.0
```

Supports Windows x86-64. Installs in `$env:LOCALAPPDATA\Yosoi\bin` and adds it to your PATH.
Open a new terminal to refresh other sessions.

### Cargo

```sh
cargo install yosoi --features cli --locked
```

Builds from source. Requires Rust 1.99 or newer and native build dependencies for your platform.

To install a specific version:

```sh
cargo install yosoi --features cli --locked --version '=0.3.0'
```

## Release candidate

The commands above select a final release. For the 0.4.0 candidate, follow the [version-specific installation instructions](../releases/0-4-0-rc-1.md). The `latest` download URL does not select prereleases.

## Verification

```sh
yosoi --version
```

See [Update and uninstall](self.md) to maintain your installation.

Use [Surface](surface.md) for persistent JSON-lines sessions, bounded web/video reads, live web actions, and archived replay.
