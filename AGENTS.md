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
