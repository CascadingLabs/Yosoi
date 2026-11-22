# Yosoi CLI

The optional `cli` feature in the `yosoi` package builds the `yosoi` command.
It lets one fetch pages, find information, search the web, discover website
pages, and manage settings from a terminal.

Install the prebuilt CLI with `uv tool install yosoi-cli`, then run
`yosoi --help`. Linux/macOS and Windows installers are published as
`install.sh` and `install.ps1` in GitHub release assets. See
[public installation instructions](../../../../../docs/public/cli/index.md).

For manual compilation, install from a checkout with
`cargo install --path crates/yosoi --features cli --bin yosoi --locked`, or run it with
`cargo run -p yosoi --features cli -- <command>`.

The experimental `yosoi surface` commands read images and videos through the shared
bounded JSON-lines protocol, and keep a live browser open for coding agents to control.
See the [public Surface guide](../../../../../docs/public/cli/surface.md) for image
pixel artifacts, video frames, references, hot cursor authority, action receipts, and
native verification.
