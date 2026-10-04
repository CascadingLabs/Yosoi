# CLI Policy profiles

The CLI reads JSON-authored Policy profiles. It provides three read-only
commands: `yosoi policy path`, `yosoi policy list`, and
`yosoi policy validate [NAME]`. The file is keyed by the exact CLI crate
version shown by `yosoi --version`. The CLI never creates or edits this file.

## Complete example for the current 0.1.0 binary

In a terminal, choose an isolated config directory and write the file:

```sh
export XDG_CONFIG_HOME="$(mktemp -d)"
mkdir -p "$XDG_CONFIG_HOME/yosoi"
cat > "$XDG_CONFIG_HOME/yosoi/policies.json" <<'JSON'
{
  "format_version": 1,
  "cli_versions": {
    "0.1.0": {
      "active_profile": "next-run",
      "profiles": {
        "next-run": {
          "page": {
            "acquisitions": [
              {
                "kind": "direct_http",
                "documents": { "kind": "current" }
              }
            ]
          },
          "request": {
            "maximum_elapsed": 15000000
          }
        }
      }
    }
  }
}
JSON
```

This selects one direct HTTP acquisition and a 15-second request deadline.
Other fields inherit this binary's `Policy::default()`. The deadline is stored
as microseconds. The `active_profile` field selects `next-run`; to use another
profile, add it under `profiles` and change that name in JSON. `validate NAME`
checks a named profile even when it is not active.

The current SDK also exposes a `map` Policy group. Omit it to inherit the
binary default; if authored in a profile, provide one complete validated Map
object. The current default shape is recorded in
[`default-policy.json`](../crates/yosoi-policy/tests/fixtures/default-policy.json).

From this repository, run:

```sh
cargo run -p yosoi-cli -- policy path
cargo run -p yosoi-cli -- policy list
cargo run -p yosoi-cli -- policy validate
cargo run -p yosoi-cli -- policy validate next-run
```

The Requests CLI is a later milestone, so validation is the operation that
consumes this profile today. A future Request command will resolve the active
profile from the same JSON store. If the file or current-version entry is
absent, the CLI uses the installed binary's defaults without writing a file.
An absent selected profile or invalid value is an error. Another version's
entry is never copied or changed automatically; migration is deferred.

On Linux, the normal store path is `$XDG_CONFIG_HOME/yosoi/policies.json`, or
`~/.config/yosoi/policies.json` when `XDG_CONFIG_HOME` is unset. The store is
limited to 4 MiB, 64 CLI-version entries, 256 profiles per version, and 128
UTF-8 bytes per profile name. Command and flag names ignore ASCII
capitalization; profile names and JSON values retain their exact spelling.
