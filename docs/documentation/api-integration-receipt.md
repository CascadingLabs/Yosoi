# API documentation integration receipt

## Integration

At Andrew's request, API documentation revision `b17b4132d69d32eb52d732b0a0ce853d1fa3f7c5` was merged with foundation revision `c5d0186d` in `yosoi/docs-foundation`. Both original revisions remain preserved. Contributor instructions retain both the foundation documentation rules and the source API documentation standard.

The frontend enum-field renderer and its regression test were merged into the existing frontend setup. The namespace-navigation tests were retained when resolving the test-file conflict. The focused reference file passes all four tests.

Work initially continued in `yosoi-docs-foundation`; the current workspace is default Yosoi. This integration does not mark the roadmap's draft teaching pages complete or implement its language-switch workstream.

## Current reference evidence

Source revision `feb52fa5e33623504a4ff75f0d654d2f6ce95ef0` contains the integrated API work and the Python alias explanation/extraction change. A new unsigned local Rust reference was generated with `browser,cli,scanner,encode-gif,encode-ffmpeg`, one Cargo worker, and the pinned documentation compiler. It contains 389 pages and passes artifact integrity verification. Compilation reported a manifest readme warning; no release or attestation was published.

The Python extractor now retains PEP 258 attribute docstrings for assignment and type-alias declarations. It does not infer descriptions from signatures. Its two focused source-extraction tests pass. Google-style checks pass for the completed Map, locator outcomes, search, identities, errors, and cancellation modules; ordinary Ruff checks pass for those modules and the alias/extractor changes.

The frontend watcher on port 4321 runs from the active frontend checkout and selects this Yosoi foundation workspace through `YOSOI_REPO_ROOT`. Its Rust artifact and source are explicitly pinned to the revision above. The prepared snapshot contains 949 pages, including 389 Rust reference pages. The 26 foundation skeletons remain drafts.

Actual served HTML was checked at:

- `/yosoi/python-api/browser/aliases/positiveu64/`: strict positive integer range, rejected coercions, and parameter-specific units.
- `/yosoi/python-api/search/types/search-request/`: the method explanation and cancellation argument.
- `/yosoi/api/yosoi/enum/responsetermination/`: separate Completed and Cancelled behavior, including the distinction between completion and acquisition success.

These are source extraction, artifact integrity, and local served-HTML checks. They are not browser interaction, hosted CI, deployed behavior, or a completed lint-enforcement claim.

## Remaining coverage

Rust source documentation gaps are filled, and SDK/derive-crate `missing_docs` enforcement is enabled. The all-features SDK check and a renamed-dependency consumer check pass with enforcement active. Python Google-style Ruff D enforcement is now enabled for the public package and passes. The public declared model-field audit reports zero missing explanations. Browser, runtime Contract, and diagnostic aliases retain adjacent source explanations. PR delivery remains pending; no PR was merged and no release was published.

## Subsequent source coverage

Request ownership, observed cancellation, document production states, typed Contract fields, schema identity, raw candidate evidence, and strict all-records validation now have Python source explanations. Google-style D checks and existing Ruff checks pass for both modules. Served HTML on port 4321 retains the ownership, completion, identity-hashing, and all-records explanations.

Rust source coverage now includes Flow validation errors, portable Contract identities and schemas, raw candidate fields, extraction outcomes and limits, field issues, and typed/runtime validation outcomes. The all-features library inventory passes compilation with the remaining warning count above. Focused Rust formatting checks pass. These new Rust comments require reference regeneration before claiming they appear in served Rust pages; the existing Rust artifact is still pinned to the earlier source revision.

A concurrent update rewrote the foundation's ancestor navigation/content work during this batch. The source edits were backed up, the workspace was refreshed, and the preserved source-documentation revision was selected with the updated ancestor retained. The foundation checker passes after reconciliation. No learning-page draft was promoted as part of this work.

Session policy fields, lifecycle, Work authority, post-dispatch uncertainty, assertion reports, Until confirmation, Flow action fields, and JavaScript dispatch now have Rust source explanations. The implementation currently rejects isolated JavaScript worlds, allows zero-duration explicit waits, and returns immediately when Work release drops its control guard. Documentation states those limits rather than implying stronger cleanup or execution guarantees.

Python document ownership, profiles, construction, policy copies, parse reuse, equality, and context cleanup now have source docstrings and field explanations. Focused Google-style and existing Ruff checks pass, and generated document pages retain the explanations. Andrew confirmed that he is managing the dev-server restarts; this task leaves the server under his control. Earlier served-HTML evidence does not establish the current server source selection.

Automation record and offline View source comments now explain recorded provenance, effect certainty, byte/count bounds, stale-source checks, and the absence of live layout or browser authority. Document profiles describe representation and schema axes separately from payload parsing. Python scalar and locator source documentation covers units, widths, strict validation, namespace bindings, query/projection compatibility, repeated-region limits, and native plan ownership.

Thirty-four literal/compatibility alias explanations were added in source. The extractor also follows assignment-based and module-qualified re-exports to their documented definitions, preserving canonical root links and source attribution. Focused extraction tests and generated-page inspections pass. The latest all-features library compilation passes with the warning count above; source comments in this batch still require final Rust reference regeneration.

## Default-workspace continuation

Andrew requested that all work be consolidated into default workspaces. Another agent completed consolidation; API documentation work resumed in default Yosoi without replacing the user-managed dev server. The learning pages, foundation ledger, reference changes, and source documentation remain present.

The populated ownership and Flow concept pages now have `needs-rewrite` inventory status rather than stale skeleton metadata. Three incoming learning pages have explicit preservation/migration dispositions. The foundation checker passes with 24 draft skeletons; no page is marked ready by this reconciliation.

Policy source documentation now covers every public class, method, and declared model field, plus 29 aliases. It distinguishes mutable authoring, Current resolution, deeply frozen snapshots, acquisition microseconds, action milliseconds, byte stages, and independent search/Map/locator bounds. Google-style D and existing Ruff checks pass; representative generated policy pages retain the explanations.

Rust SDK `missing_docs` is denied after filling the public inventory. The re-exported Contract derive crate has its own denial and source documentation. A consumer fixture denying missing documentation initially detected the generated candidate struct; adding meaningful generated struct/method documentation and inherited field descriptions made that check pass. The all-features SDK check passes; the default-feature consumer check reports two existing dead-code warnings, distinct from missing documentation. These are local compile checks, not hosted CI or runtime/browser certification.

## Completed Python source coverage

Browser and runtime Contract modules now have Google-style public class, constructor, method, and function documentation. Model fields describe units, evidence, ownership, bounds, and limitations. Session acquisition is lazy; Work release awaits native settlement without closing its owner; cooperative cancellation preserves partial and unknown effects without rollback. Runtime views complete schema field mappings while serialization retains the original Rust wire. require_all() rejects incomplete evidence, phase failures, field issues, and extraction diagnostics instead of returning a successful subset.

Package-wide Ruff passes with D rules enabled. The separate declared-field audit finds no missing explanations. An AST comparison against the consolidated parent proves that the browser, runtime Contract, and diagnostics edits change documentation expressions only. Two extraction tests pass, and generation produces 486 Python API pages. Inspected Work, SessionPolicy, and RuntimeContractOutcome Markdown retains method prose and model-field explanations. These checks do not prove new content is served on the user-managed frontend or deployed. Final Rust artifact regeneration and PR delivery remain pending.

## Source documentation delivery

The public Python inventory is complete and Google-style Ruff D enforcement is enabled. Rust SDK and derive enforcement remains enabled. The refreshed unsigned Rust artifact from `e3df268213c60378ee923a838b24be05d0954233` has 389 pages, passes integrity verification, and retains both ResponseTermination variant explanations, 255 documented nested variant fields, and Contract derive prose. Python extraction has 486 pages. The prepared frontend contains 959 pages. Served port-4321 HTML now verifies the refreshed Rust SHA and ResponseTermination prose as well as the new Python Work, SessionPolicy, and runtime outcome explanations. The server remained under Andrew's control.

Source-documentation PR [#158](https://github.com/CascadingLabs/Yosoi/pull/158) is based directly on current main and excludes the release navigation and learning-page work. The consolidated default working copy remains selected and retains all work. Push hooks pass. Nine Rust model tests, two Python extraction tests, and 21 documentation tooling tests pass locally. Shared Markdown validation passes; the shared format gate reports unrelated review/concept-page failures. Hosted CI started on the PR and is not claimed green. No PR merge, release, or deployment occurred.
