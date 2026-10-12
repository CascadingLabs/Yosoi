# Foundation delivery receipt

## Scope

The foundation adds 34 destination records, 26 new draft pages, 54 legacy dispositions, public authoring rules, a roadmap, worker and review templates, a paired-example template, and a lightweight checker.

The source basis is the current local public Rust and Python code inherited from the active documentation workspace. The initial parent was `86763cf263207079f44d8c5c8213807fa50078b3`. Concurrent reference and release updates rewrote that parent to `e1cf1006`; the foundation was recovered and retained on its own bookmark, `yosoi/docs-foundation`.

## Code inspection

- Rust document construction and accessors: `crates/yosoi/src/documents.rs`.
- Rust document identity accessor: `crates/yosoi/src/internal/documents/document.rs`.
- Python constructor, identity and retained data: `python/yosoi/documents.py`.
- Public namespace and capability boundaries: `crates/yosoi/src/lib.rs` and `python/yosoi/__init__.py`.
- Every destination lists specific existing code authority in `page-map.json`.

The paired document example uses Rust `bytes()` and Python `data`. These are inspected public accessors, not assumed mechanical translations. Example execution is still required before this template becomes a finished public page.

## Focused verification

- Foundation checker passed with all destinations and legacy assignments accounted for.
- Negative smoke checks rejected a missing authority file, a skeleton with `draft: false`, an em dash, and an unsupported installation command. Temporary mutations were restored.
- Changed Markdown, JSON and the new checker were formatted with one worker.
- Public docs validation passed, including generated Python reference, navigation, links and native Markdown rendering.
- Whitespace diff checks passed.

## Remaining work

The clickable Rust/Python changer is a specified frontend workstream. It has not been implemented or browser-tested here. Full topic rewrites, snippet execution receipts, browser journeys, navigation cutover and publication remain roadmap work.

The current sidebar is unchanged. Reference and release-note files have no foundation diff. The new skeletons remain drafts and are excluded from public collection.
