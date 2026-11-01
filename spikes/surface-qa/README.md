# Surface QA: automatic execution before click-tree optimization

Session decision: 2026-10-26 evening (ET), 2026-10-27 UTC.

- [Next experiment: CAS-636](https://linear.app/cascadinglabs/issue/CAS-636/shape-automatic-surface-qa-execution-with-assertions-and-bounded)
- [Evidence and policy implementation: draft PR #177](https://github.com/CascadingLabs/Yosoi/pull/177)
- [Separate per-tab recording spike: draft PR #170](https://github.com/CascadingLabs/Yosoi/pull/170)
- [Recording-spike findings and QA follow-up](https://linear.app/cascadinglabs/document/native-browser-and-concurrent-per-tab-av-spike-findings-and-reviewed-688521fc8433)

## Direction

Andrew used Thinking Fast and Slow / System 1 and System 2 as a design analogy.
The model chooses the intended outcome. A fast execution layer performs ordinary
target resolution, clicks, fills, bounded waits, assertions and evidence collection.
Deliberate reasoning handles genuine ambiguity, unresolved failures and consequential
choices. Routine mechanics should not require a separate model decision each time.

First get this automatic loop working on useful tasks. An internally verbose clicking
tree is acceptable initially if it executes locally without repeated model round
trips. Optimize the internal tree, capture strategy and transport after reliable task
completion. The primary metric is model interventions per verified completed task;
command count is a later optimization metric.

Keep one `yosoi surface` command tree and package QA behavior as an agent skill.
Support direct Rust/Python SDK use, direct CLI use, and ad hoc Shell/Lua/Python/Node
scripts composing CLI calls. Stable JSON, process behavior and retained-session
addressing matter to the scripting use case.

Reuse Flow, nested flows, assertions, bounded Until waits, receipts and Session/Work
ownership. The next slice is integration and packaging of existing primitives.
A new assertion engine or query DSL is not the starting requirement.

## What exists locally

Code checkpoint `9fbb3b92d49201bd629dc7b79c8dfd56488ed616` in PR #177 adds native
Chrome AX and bounded network event views to browser Surface. SDK policy configures
retained bytes, tree depth, node count, overview depth and response bytes separately
for DOM, AX, HTML, XML, JSON, text and network documents.

The current browser Surface provider uses ChromeDriver. AX/network evidence is
read-only; actions require DOM references. Network response bodies are not collected,
and window completeness is unestablished. Captures across representations are
sequential. These features do not implement an automatic QA executor or agent skill.

Local evidence includes 23 Python Surface tests, six matching Rust/Python document
vectors, focused Rust limits/reference/depth/replay tests, live docs SDK/CLI probes,
and a portable archive replay with browser executables disabled.

## Live docs journey and friction

The live journey succeeded: open Search; verify its dialog/textbox through AX;
enter `documents` and confirm the input value; wait for results; verify the first
ordered result; click DocumentOutcome; confirm its URL and heading.

The exploratory run used **37 CLI commands** and approximately **6m49s** from the
first ready reply to close. Trace milestones from process launch:

| Milestone | Approximate elapsed time |
| --- | ---: |
| Search control identified through AX | 1m22s |
| First-result ordering verified | 5m43s |
| Destination URL/heading verified | 5m53s |

These include model reasoning, tool orchestration and debugging. They are not
browser-only timings or an optimized benchmark. One overlapping command affected
request/latency labels, so do not quote a summed CLI latency or total token comparison.
The Search click was about 598ms and fill about 865ms including associated capture work.

Observed friction:

- AX depth 8 included the dialog/textbox but excluded result links; deeper or better
  scoped evidence is needed for that region.
- AX discovery required another DOM lookup before acting.
- Focus, refresh, inspection and parent traversal were exposed to the model.
- An ad hoc script mechanically followed producer-issued parents and verified
  first-item ordering. The execution layer should handle that bookkeeping.
- Browser work, capture, transport and model time were not cleanly separated.

Local transcripts remain in `.local/docs-live-flow/steps.jsonl`,
`.local/docs-live-flow/evidence/trace.json` and `.local/docs-live-flow/result.json`.
They are ignored local evidence, not committed artifacts. The raw run is not a fully
automatic or portable executable QA recipe.

## Next vertical slice: plan only

Make one automatic invocation complete the docs search journey with assertions and
useful failure evidence. Let it run predictable steps without model round trips.

1. Use the same retained tab for Surface evidence and existing Session/Work/Flow execution.
2. Resolve semantic/AX targets into fresh eligible action targets internally.
3. Combine act, event-driven bounded wait, assertion and scoped after-state.
4. Recover from routine stale evidence within bounded rules. Never blindly repeat an
   effect with an uncertain outcome, especially a non-idempotent action.
5. Escalate ambiguity, failed/unsupported assertions, exhausted recovery budgets and
   consequential choices. Preserve freshness and single-owner action authority.
6. Demonstrate SDK, CLI and mixed-script usage, then teach the QA skill those interfaces.

Acceptance should include a controlled fixture, the live docs search, a deliberately
failed assertion, rerenders and delayed results. Avoid fixed readiness sleeps.
Measure verified completion, interventions/fallbacks, end-to-end time, model decision
time, browser dispatch/settlement, capture/projection, serialization/transport,
context consumption and resource use separately. Do not promise human-equivalent or
sub-100ms execution without measurements.

Dogfood for a few weeks on QScrape and Yosoi docs, then Andrew's authorized work
website. Record actionable recurring failures as regressions. Per-tab recording and
secret masking are subsequent integration work; their readiness is separate from
the new evidence views and automatic executor.

## Stop boundary

This is a documentation and planning checkpoint. The automatic executor and QA skill
are not implemented or authorized for further work tonight. Andrew explicitly waived
CI follow-through for the session; current-head hosted CI is not claimed fully green.
PR #177 remains draft. No merge, release, deployment or ticket completion is implied.
