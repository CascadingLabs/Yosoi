# Engineering

- Write simple, idiomatic Rust with explicit domain types and straightforward control flow; avoid unnecessary abstractions and generics.
- Use `thiserror` for domain/library errors; reserve `anyhow` with context for application boundaries.
- Production code must not panic: avoid `unwrap`, `expect`, unchecked indexing/slicing/arithmetic; encode invariants in types where practical.
- Synchronize through events, channels, notifications, or task completion. Never use `sleep` for readiness, retries, or polling; timeouts only bound waits.
- Make internal changes forward-only: update callers atomically and remove obsolete shims. Preserve compatibility only for known external consumers, persisted artifacts, or wire contracts; identify breaking boundaries in the handoff.

# Resource safety

- Run one expensive command at a time, with one worker by default. Prefer focused checks; do not repeat passing checks without a change.
- If slowdown, swap pressure, instability, or unexpected fan-out occurs, stop expensive work, inspect memory/processes, and reduce concurrency. Report skipped/stopped checks.

# Browser stack

Read and follow [the Chromium/CDP baseline](docs/chromium-cdp-baseline.md) before changing Chromiumoxide, generated bindings, browser selection, launch arguments, or stealth. It owns the certification procedure, version matrix, monthly review, and release evidence.

- Use regular Chrome/Chromium Stable only. Testing-only distributions are forbidden, including diagnostics. More than one Stable milestone or 30 days behind is uncertified.
- Preserve sandboxing and site/process isolation. Security exceptions require explicit, typed, measured justification and separate approval.
- Record VoidCrawl, Chromiumoxide, CDP schema, and browser identities separately. Investigate every invalid/dropped CDP message; never treat `ignore_invalid_messages` as compatibility evidence or claim speed/stealth gains without measurement.
- Keep Chromiumoxide and a small documented patch queue; a replacement requires a concrete issue proving bounded patches insufficient.
- Review on the first business day monthly and after relevant security/compatibility changes. Record a go/no-go/urgent-remediation decision, consumer notes, and deduplicated follow-ups or dismissal reasons. Promotion requires complete applicable regressions and Rust benchmarks, run serially.

# Release procedure

- Beta releases stay below `1.0.0` and use `0.MINOR.PATCH`, without a `-beta` suffix. Beta iterations increment MINOR (1–100000) and reset PATCH to zero: `0.1.0`, `0.2.0`, …, `0.100000.0`.
- Bug fixes and hotfixes increment only PATCH (1–10000) within the current beta iteration: `0.2.0` → `0.2.1` → `0.2.2`. The next beta iteration becomes `0.3.0`. Reserve `1.0.0` for the first stable release.
- Preview with `cargo xtask bump-version 0.2.0 --dry-run`, then run `cargo xtask bump-version 0.2.0` to update in place. Use the actual chosen version in both commands.
- A real run validates the metadata and stages complete replacements beside the originals before asking `Apply these changes? [y/N]`. This checks file preparation, not compilation, dependency resolution, or release test results. Answer `y` or `yes` to apply; `n`, `no`, an empty answer, or end-of-input cancels. Use `-y` or `--yes` for scripting (for example `cargo xtask bump-version 0.2.0 --date-released 2026-10-04 -y`); staging and validation still run. `--dry-run` and `--check` never prompt or stage files and cannot be combined with `-y`.
- Applying rechecks the originals for concurrent edits, preserves permissions, and replaces each file with an atomic rename. Ordinary replacement failures restore already updated files. The entire multi-file update is not atomic across process termination; inspect the diff and rerun the consistency check after an interruption.
- The command synchronizes `[workspace.package].version`, every first-party package under `crates/`, `benchmarks/`, `xtask/`, and `fuzz/`, local dependency requirements (including renamed and target-specific dependencies), `Cargo.lock`, `fuzz/Cargo.lock`, and `CITATION.cff`. Vendored Chromium manifests and dependency versions retain their independent identities. Dependency requirements use `=VERSION` so beta dependencies resolve to the chosen iteration.
- Verify with `cargo xtask bump-version 0.2.0 --date-released 2026-10-04 --check` (fails on version or date drift), using the chosen release version and date. Review the diff and run the focused release checks. The command does not build product crates, resolve dependencies, create tags, or publish releases. Keep existing unrelated changes intact.
- Set `CITATION.cff`'s `date-released` through `cargo xtask bump-version 0.2.0 --date-released 2026-10-04`, using the actual release version and date. The date must be a valid calendar date in `YYYY-MM-DD` format. Combine this option with `--dry-run` to preview or `--check` to verify both version and date; omit it to preserve the existing date. The CFF schema version stays unchanged. Example versions in docs, historical evidence, and generated reference artifacts are not release metadata and are not rewritten.


## Local release notes contract

- Prepare numbered release-note drafts with `cargo xtask release prepare VERSION --date YYYY-MM-DD --channel preview --github-notes EXPORT.md`, adding `--previous VERSION` when applicable. The Jinja template and pinned environment live under `scripts/releases/`. Preparation must not overwrite an existing draft or its provenance record.
- Keep the reviewed Markdown under `docs/public/releases/` as the canonical notes. Preserve the imported GitHub change references, contributor mentions, and first-time contributor recognition. Remove editorial placeholders and mark `draft: false` only after review.
- Run `cargo xtask release check VERSION` after synchronizing versions and the citation date. It verifies finalized notes, imported attribution, and the existing release metadata consistency contract. `body VERSION` exports validated Markdown; `history` refreshes the docs index from finalized entries and excludes drafts.
- These commands do not tag, publish, build release binaries, upload to registries, or manage nightly artifacts. Only the explicitly requested `fetch` command accesses GitHub, read-only, with an explicit comparison range.

# Linear

`Backlog` → `Todo` → `Shaping` → `Ready for Worker` → `Agent Working` → `In Review` → `Agent Verification` → `Final Boss` → `Ready to land` → `Done`

- Shape scope, acceptance, dependencies, and validation before work. Independent review follows implementation.
- The parent owns the primary issue's status; subagents manage distinct issues only when delegated.
- Verification: pass → `Final Boss`; code fixes → `Agent Working`; scope changes → `Shaping`; relinquished ready work → `Ready for Worker`.
- Only Andrew moves `Final Boss` → `Ready to land`. The landing agent marks `Done` after landing and verifying the final state. Disclose gaps; blocked work retains its phase with a blocker and unblock condition.
- From `Agent Working` onward, comment on transitions with revision/PR, validation, gaps, and next owner.
- New or substantially rewritten issues need a native **Plain English** callout near the top: 2–4 short sentences explaining the change, value, and expected result. Put technical details below; verify the callout after saving. API/Markdown form:

```markdown
<!-- linear:callout icon=Lightbulb -->
> [!NOTE]
> **Plain English**
>
> Human-readable explanation.
```
