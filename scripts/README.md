# Repository scripts

Use `cargo xtask bump-version <VERSION>` to synchronize first-party release
versions, local dependency requirements, lockfiles, and `CITATION.cff` in place.
`--dry-run` previews affected paths; `--check` fails if any version needs updating.
Add `--date-released YYYY-MM-DD` to update or check the citation's release date
alongside the version. Omitting it preserves the existing date.
Real runs stage replacements and ask for yes/no confirmation. Pass `-y` or
`--yes` to apply after staging without prompting in scripts. Preview/check modes
remain read-only and do not accept the confirmation flag.
See the release procedure in the root `AGENTS.md`.

Maintained JavaScript documentation tooling lives in `docs/`:

- `cargo xtask docs manifest <command>` generates public-document manifests.
- `cargo xtask docs reference <command>` owns SDK reference workflows under `docs/reference/`.
- `cargo xtask docs check` runs their focused tests serially.

`bootstrap.sh` installs the pinned Rust development tools. Standard maintenance
lives in Rust `xtask`: SDK boundary checks, capture measurements and result
retention, fixture integrity/materialization, and the serial fuzz smoke profile.

The Search, Map, benchmark, browser, fixture-generation and independent Python
oracle harnesses are retired. Committed fixture bytes and expected values remain
under `benchmarks/fixtures`; Rust regression tests own semantic behavior. Existing
benchmark results and documentation artifact locations remain unchanged.

## Release notes

Use `cargo xtask release prepare VERSION --date YYYY-MM-DD --channel preview --github-notes EXPORT.md`
to scaffold a local draft from GitHub-generated notes. Choose `--previous VERSION`
explicitly for the desired earlier comparison baseline; omit it only for the
first tracked release. Review the prose and retain the imported
attribution section, then set `draft: false`.

After synchronizing the chosen version and citation date with `bump-version`,
run `cargo xtask release check VERSION`. This checks the reviewed notes and the
existing complete version/date consistency contract. Export the reviewed body
with `cargo xtask release body VERSION`; refresh the public history with
`cargo xtask release history`.

The pinned Jinja environment requires `uv`. See
[`releases/README.md`](releases/README.md) for the template, offline input format,
read-only GitHub export, and validation commands. These commands do not create
tags, publish releases, upload packages, build binaries, or manage nightlies.
