# Release notes tooling

This local Python project prepares public release-note drafts from an exported
GitHub release-notes body. `Jinja2` is pinned in `pyproject.toml` and
`uv.lock`; `uv run --locked --project scripts/releases` supplies that runtime.

```sh
uv run --locked --project scripts/releases python scripts/releases/release.py --root . prepare 0.2.0 --date 2026-10-04 --channel preview --previous 0.1.0 --github-notes /tmp/0.2.0-github-notes.md
uv run --locked --project scripts/releases python scripts/releases/release.py --root . check 0.2.0
uv run --locked --project scripts/releases python scripts/releases/release.py --root . check 0.2.0 --json
uv run --locked --project scripts/releases python scripts/releases/release.py --root . body 0.2.0
uv run --locked --project scripts/releases python scripts/releases/release.py --root . history
```

`prepare` requires an explicit notes export and creates a draft plus a hidden
provenance sidecar. It refuses to replace either file, so editing and rerunning
cannot erase reviewed prose. Set `description` to a one-sentence value summary
because history uses it. Finish the Summary and Upgrading sections, retain the
complete imported credits and links, omit empty optional sections, set
`draft: false`, then use `check`. A Highlights section is scaffolded and may be
removed for a small patch; if present, fill it with user-facing prose. `body`
validates the same finalized-note contract before writing only the Markdown
body to stdout.

`fetch` is the only subcommand that calls GitHub's generated-notes API. It uses
`gh` only when explicitly requested and requires the repository, previous tag,
target ref, and output path:

```sh
uv run --locked --project scripts/releases python scripts/releases/release.py fetch 0.2.0 --repository owner/repo --previous-tag v0.1.0 --target-ref main --output /tmp/0.2.0-github-notes.md
```

The previous tag and target ref are never inferred. `previous` is an explicit
earlier comparison baseline, not necessarily the highest version: for example,
a recommended release may compare against the previous recommended release
rather than an intervening preview. Omit it only for the first tracked release.
The fetched body is saved as an offline input. `uv run --locked` may download
pinned tooling dependencies on first use; after provisioning, set `UV_OFFLINE=1`
on `uv run --locked` to keep prepare, check, body, and history fully offline.

The release page in `docs/public/releases/` is the canonical publication
source. The xtask release wrapper additionally checks workspace and citation
metadata; this Python `check` validates the notes page and imported source only.
`history` includes finalized pages only and updates an existing index only when
its generated-content checksum proves the file has no manual edits.

The complete GitHub body, including contributor credits, PR links, and compare
links, remains in a `prettier-ignore-start` / `prettier-ignore-end` region.
The docs formatter was probed with a release-note fixture and preserved that
region byte-for-byte, so its provenance digest remains stable. Editorial TODOs
inside examples are ignored by validation when they are inside fenced or inline
code; TODOs in title, description, Summary, Highlights, or Upgrading must be
resolved.

Run the focused unit tests from the repository root. Workspace-local temporary
storage also avoids workstation `/tmp` quota limits:

```sh
mkdir -p .generated/release-tests
TMPDIR="$PWD/.generated/release-tests" UV_OFFLINE=1 uv run --locked --project scripts/releases python -m unittest discover -s scripts/releases/tests
```
