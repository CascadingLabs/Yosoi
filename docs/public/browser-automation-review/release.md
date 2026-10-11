---
title: 'What earns a 0.2.0 release'
description: '0.2.0 release preparation, supported scope decisions and remaining verification.'
order: 9
---

# What earns a 0.2.0 release

## October 10 preparation checkpoint

The default workspace, `/home/andrew/Desktop/cl/Yosoi`, now combines browser
actions, native nested timeout scopes, immediate Rust assertion groups and both
Qscrape examples. The previous assertion integration and timeout revision remain
separate parents, preserving their review history. This checkout is the active
browser automation integration workspace.

Focused checks on the combined code pass: seven executor tests, ten Flow-model
tests, four automation-record tests and four assertion-group tests. The combined
browser tests compile. Two focused hardened-container controls also pass: the
longer child timeout and an assertion group that blocks the next click on failure.
These use the existing Chrome 153.0.8010.36 spike image; current Stable release
certification remains separate. Nested saved
assertion descriptors are checked before browser acquisition; they remain
inspectable but require explicit Rust predicate rebinding to execute.

### Decisions to make next

| Decision                   | Recommendation to review                                                                                                                             | Issue            |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| Release completion API     | Distinguish a release request from confirmed safe handoff; retain the agreed fence-and-error default for unresolved borrowed tabs.                   | CAS-570          |
| Deferred assertions        | Scoped Until is implemented locally; review [its current evidence and live-navigation limitation](until.md) before release inclusion.                | CAS-572          |
| Archive and Views in 0.2.0 | Ship bounded records and inspection only if their integrity and installed-artifact checks pass; defer stronger durable/replay guarantees.            | CAS-566, CAS-567 |
| Python release scope       | Require parity for the core shipped Rust API, including optional lease, timeouts and cancellation; decide supported platform/interpreter guarantees. | CAS-574          |

Already agreed: integer timeouts are milliseconds, nearest scope wins, Stop
returns a structured in-execution outcome, parked Flows retain exclusive tab
ownership while yielding worker capacity, and unresolved borrowed cleanup leaves
the tab fenced and returns an error. JS files and bounded local modules are also
approved for implementation now (CAS-573), with construction-time snapshots and
explicit managed permission. Those choices need no repeat decision.

Failure and local child cancellation now default to Continue, with independent
nearest-scope overrides through Stop(CurrentFlow) and Stop(Invocation). An
explicit Continue overrides a global Stop. CAS-569 implements this approved
contract; a cancelled child never resumes its own subtree, while its parent can
continue. Root/Session cancellation and uncertain dispatch remain hard boundaries.

### Release preparation checklist

- [x] Integrate browser actions, assertions, examples and timeout scopes in default.
- [x] Run focused model, executor, record and assertion checks on the combined code.
- [x] Preview `cargo xtask bump-version 0.2.0 --dry-run`; 24 metadata files need
      updating. No release version or date has been applied.
- [x] Compile browser integration cases on the combined code.
- [x] Compile `qscrape_checkout`, `qscrape_cart_assertion`, `assertion_groups`
      and `browser_automation_spike` with the browser feature on the combined code.
- [ ] Reconcile this branch with current `main` before building release artifacts.
      The inspected `main` is `38f601f4` and has Python parity, release CD and docs
      publication changes absent from this local branch. Integrate through review;
      do not replace those changes with the older browser base.
- [ ] Freeze the shipping matrix and finish the required lifecycle behavior.
- [ ] Verify current regular Stable Chrome and supported browser/controller identities.
- [ ] Run controlled cancellation, contention, fencing and cleanup cases on the
      final integrated source; then run live stateful and multi-tab examples.
- [ ] Build/install supported Python wheels and exercise the shipped SDK from
      clean consumer environments. Rust model checks do not establish Python parity.
- [ ] Apply the approved version/date through the existing `bump-version` command
      after the shipping scope is frozen. A dry-run is preparation, not an applied bump.
- [ ] Prepare canonical numbered notes through `xtask release prepare`, retaining
      imported change references and contributor attribution. Choose the actual
      published comparison baseline first; do not invent a `v0.1.0` release.
- [ ] Run focused release consistency checks, required hosted CI and artifact
      verification, then present the publication decision with explicit evidence gaps.

The GitHub release list inspected on October 10 still has `v0.0.3a27` as its most
recent published entry. `main`'s rc.2 preparation is not a published release.
The release-note comparison baseline, channel and publication date remain to be
finalized. Preparation does not create tags or publish packages.

The local spike proves a useful integration. A release needs a stable contract,
practical examples and failure-path evidence for the supported environments.

## Recorded evidence

The October 5 handoff reports, and the saved logs confirm:

- 18 browser safety tests passed in the hardened Yosoi Docker environment.
- 2 integrated browser/fresh-process replay tests passed.
- Focused Flow, Archive, View and existing SDK checks passed.
- The facade compiled without the browser feature.

Those are controlled Rust results. They do not establish Python wheel readiness,
real-site reliability, performance, all-platform support or production readiness.
They have not been rerun for this review site.

## Proposed core scope

Sessions and tab ownership; Work leases; browser Request reuse; typed actions;
sequential Flows and assertions; explicitly permitted JavaScript; bounded
operation receipts and honest failures. Python should expose that same model.

Archive and Views need an explicit release decision. Firefox/BiDi is out of
current scope. Remote attachment, distributed placement, isolated JS worlds and
continuous network/AX streams are not implemented release capabilities.

## Before landing

1. Resolve the decisions in this guide and write the final supported contract.
2. Complete the serious implementation pass: foreground coordination, terminal
   and cleanup evidence, required subscriptions, memory budgets and provenance.
3. Build and test the Python API against the same ownership and outcome rules.
4. Exercise a real stateful workflow, dynamic page, multi-tab workflow and
   JavaScript Flow. Pair live examples with controlled negative cases.
5. Verify cancellation, browser failure, contention, watcher lag and large
   captures. Verify Archive corruption and fresh-process replay if included.
6. Recheck existing Request behavior and the current Stable Chrome baseline.
7. Build the supported packages and install the Python wheel in a clean consumer
   environment. Run the published examples with those installed artifacts.
8. Finalize docs, version metadata, release notes and required CI before the
   release decision. Run one expensive validation command at a time.

## Decision to review

Is this the right 0.2.0 scope? Tell me yes, no or needs discussion for each topic in chat, with a
short note explaining changes. The guide
does not automatically authorize implementation, landing or publishing.

**Recommendation:** settle the public contract first, then implement and test
against it. Your review should determine the next pass rather than simply bless
the current spike.
