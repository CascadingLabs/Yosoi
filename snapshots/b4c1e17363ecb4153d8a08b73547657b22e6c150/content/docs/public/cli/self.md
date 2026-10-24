---
title: 'Update and uninstall'
description: 'Maintain the Yosoi CLI using its installation method.'
order: 1
---

# Update and uninstall

These commands are intended for 0.3.0. To upgrade a released 0.2.1 installation,
rerun its standalone installer or use UV or Cargo.

## Update

```sh
yosoi self update
```

For a standalone installation, Yosoi asks before updating to a newer stable release.
Press Enter to accept `[Y/n]`, or enter `n` to cancel. The download is checked
against the release checksum and its version is verified before replacing the
installed executable.

An implicit update keeps a newer release candidate when the latest stable release
is older. To select a specific release, including a downgrade:

```sh
yosoi self update --target-version 0.3.0
```

Use `--yes` to skip confirmation. Non-interactive sessions require it:

```sh
yosoi self update --yes
```

## Uninstall

```sh
yosoi self uninstall
```

Yosoi asks before removing a standalone installation. Press Enter to cancel
`[y/N]`, or enter `yes` to confirm. It removes the executable and its installation
receipt. Configuration, saved evidence and other files in the installation
directory remain.

To uninstall without a prompt:

```sh
yosoi self uninstall --yes
```

## UV and Cargo installations

For a package-managed installation, either command prints the corresponding
UV or Cargo command. Yosoi leaves those files to the package manager. The printed
instructions include the detected installation directories so a custom
installation is maintained in the correct place.

UV installations use `uv tool upgrade yosoi-cli` and `uv tool uninstall yosoi-cli`.
An explicitly selected version uses `uv tool install --force` instead; ordinary
UV upgrades retain the version constraints used during installation.
Cargo installations use `cargo install yosoi --features cli --locked` and
`cargo uninstall yosoi`, with the detected `--root`.

A command run through `uvx` has no permanent tool installation to uninstall.
Run it again through `uvx` to use the package selected by UV. Other Python
environments must be maintained through their own package manager.

## Windows completion

Windows keeps a running executable locked. Yosoi starts a helper and reports
that maintenance is scheduled after it exits. The command prints the path to a
JSON result file. Read that file to check whether the operation succeeded:

```powershell
Get-Content -LiteralPath 'C:\path\printed\by\yosoi.json'
```

The result changes from `pending` to `success` or `failed`. A failure includes an
error message. The helper waits up to 60 seconds for Yosoi to exit.

Uninstall removes a Windows user PATH entry only when the standalone installer
added it and the installation directory contains no other files. Open a new
terminal to refresh its PATH. Linux and macOS uninstall leave shell PATH settings
in place because the installer does not edit them.

## Changing installation methods

Uninstall through the current installation method, then use the new one. For
example, remove a UV installation with `uv tool uninstall yosoi-cli` before
installing through Cargo. Run `yosoi --version` afterward to check the executable
your shell selects.

Standalone maintenance requires a matching installation receipt. Older
standalone installations without a receipt can be reinstalled using the
[installer](index.md). An unknown installation or a receipt that no longer
matches the executable is left unchanged. A stale receipt does not override UV
or Cargo ownership.

If an interrupted operation leaves `.yosoi-maintenance.lock` in the installation
directory, check that the installer or maintenance helper has stopped before
removing the lock and retrying.
