# Chromium, Chromiumoxide, and CDP baseline

Status date: 2026-09-15. CAS-373 is the accepted milestone-5 compatibility
baseline and is ready for Final Boss review.

## Stable launch eligibility review, 2026-10-10 UTC

Google's Linux Stable release history now serves Chrome 155.0.8059.39, released
2026-10-06. The CI installer downloaded that regular Stable package, but the
2026-10-04 launch-eligibility snapshot did not include it, so the runtime
rejected it before launching. The snapshot now includes M155 and the preceding
M154 releases, retaining the independent 30-day snapshot and superseded-release
limits. M153 is now two milestones behind and is no longer eligible for launch.

This updates distribution and age admission; it does not promote a new
browser/controller/CDP certification tuple. The M153 certification below is
historical evidence. The decision is to admit reviewed Stable releases for
regression testing; certification promotion remains pending. M155 regressions run in CI against regular Stable with
sandboxing and isolation preserved; native/headful/container and benchmark
certification remain separate release work. No generated bindings, controller
patches, browser flags, or invalid-message handling change in this refresh.

Focused local evidence uses regular Google Chrome 155.0.8059.39 from Google's
Stable Debian download: package SHA-256
`c58aa0f2cd66179c9f050e062c882d27aa9b9f8c2b7c73fee3498560b5ed0b38`,
executable SHA-256
`9bfb381296dffe75f3419d07b6cc64525105ed117d1453a4ef3b291cb97d2b58`.
The three distribution/age tests pass, as do all seven engine browser
integration tests, including mixed Direct HTTP/headless/headful acquisition
and cross-process archive reconstruction. The TCP reset fixture regression
also passes. Strict Clippy passes for the affected library and test targets.
These focused results do not replace full certification.

Sources: [Google Linux Stable version history](https://versionhistory.googleapis.com/v1/chrome/platforms/linux/channels/stable/versions/all/releases)
and [the 2026-10-06 Stable announcement](https://chromereleases.googleblog.com/2026/10/stable-channel-update-for-desktop_086471744.html).

## The four identities

Yosoi's browser stack has four independently moving identities. Do not call all
of them the "CDP version."

| Layer | Current repository/runtime identity | What it controls |
| --- | --- | --- |
| VoidCrawl controller integration | Private module `crates/yosoi/src/internal/browser` | Yosoi-facing browser primitives, bounds, cleanup, and effective instrumentation policy; the controller component identity remains `yosoi-browser-core` |
| Chromiumoxide controller | vendored `chromiumoxide` 0.9.1, based on upstream commit `a7e2bb835b9643410f9e3dc044f0d947e96cbfa4` | CDP transport, target/session routing, page lifecycle, and event delivery |
| Generated CDP bindings | vendored `chromiumoxide_cdp` `0.10.0-yosoi.m153.1`, generated from Chrome 153.0.8010.36 at schema revision `r1681091` | The Rust command, event, enum, and payload shapes known at compile time; the local 0.10 version records the intentional M145-to-M153 public schema break |
| Chromium executable | certified regular Google Chrome Stable 153.0.8010.36; Chromium 152.0.7977.82 is the rollback comparison | The browser engine, security fixes, renderer behavior, web platform, and externally visible browser fingerprint |

The previous registry schema was `r1566079`, mapping to Chromium 145.0.7623.0.
The first candidate instead vendors the exact Chrome 153.0.8010.36 browser PDL
and its DEPS-pinned V8 PDL at Chromium revision `r1681091`. Chromiumoxide
0.9.0's optional fetcher points at `r1585606`, Chromium 147.0.7693.0, but
VoidCrawl depends on Chromiumoxide with default features disabled and does not
use that fetcher as its browser baseline. Chromiumoxide remains 0.9.1; the
generated CDP package uses the local pre-release version
`0.10.0-yosoi.m153.1` to make its breaking schema change explicit. Neither
package version is a Chromium version.

Native and container evidence now bind the same regular Stable executable and
SHA-256 digest. The container still starts from the local runtime tag
`voidcrawl-headful:local`, but its runner refuses to build unless that tag
resolves to the reviewed image ID
`sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a`,
labels the result with that identity, and verifies exact layer ancestry.
The certified image used the Linux/amd64 Rust 1.98 builder manifest pinned at
`sha256:af753e6e729c839de28010e323abc550eceaa9572bdaa765429d4f585e2e43dc`.
The certified resulting image ID and in-image browser digest are recorded
below.

As of 2026-10-04, both checked-in Docker builders use Rust 1.99.0 with
Linux/amd64 manifest
`sha256:9d5e02aa6c7e9c112ed7a4c438900b41f519a792959cd5445c25de42bfb8388b`,
resolved from the official `rust:1.99.0` image. Rebuilding and certifying those
images remains pending; the historical image evidence below applies to its
recorded Rust 1.98 builder. Browser, CDP, Chromiumoxide, and VoidCrawl identities
are unchanged by this compiler update.

## What protocol age means

`chromiumoxide_cdp` is generated client-side Rust code. Its schema revision is
not transmitted in an HTTP header, JavaScript property, user agent, or CDP
handshake. A page or anti-bot service cannot directly read that Yosoi compiled
against `r1681091`. The previous registry dependency compiled against
`r1566079`.

Schema lag still matters. A newer browser can add fields or enum values, rename
experimental fields, deprecate commands, or change target/event behavior. An
older generated client may then reject or drop a message, omit a capability,
or require a workaround with observable effects. Chromiumoxide pull request
305 is a concrete example: it updates the schema to `r1596832` (Chromium
148.0.7728.0) because a newer `Network.requestWillBeSentExtraInfo` payload can
fail deserialization with the older bindings. The certified M153 surface did
not reproduce that decode failure; any future invalid message still triggers an
out-of-cycle compatibility review.

Updating the schema provides current types and compatibility knowledge. It
does not inherently make navigation faster or make the browser less
detectable. CDP's stable protocol label `1.3`, including the
`Browser.getVersion().protocolVersion` value, is also not the compiled schema
identity; record the PDL/Chromium revision separately.

## What browser age means

The executable is different. Websites can observe or infer its user agent and
client hints, JavaScript and DOM behavior, supported APIs, rendering and WebGL
behavior, TLS/network behavior, permissions, plugins, headless behavior, and
automation-related state. An old or internally inconsistent browser identity
can contribute to detection. More importantly, Chromium security fixes live in
the executable, not in the Rust CDP bindings.

The target is current security-updated Chrome/Chromium Stable. A newer browser
is not automatically faster or stealthier: it can also introduce new
fingerprint surfaces, CDP payloads, headless behavior, or regressions. Promotion
therefore requires measurement against an exact executable rather than an
assumption that a higher version is always better.

Chrome for Testing and every other testing-only distribution are prohibited for
all Yosoi execution. There is no diagnostic exception. Certification,
deployment, benchmark-promotion, support, and release evidence must use a
security-updated regular Chrome/Chromium Stable distribution intended for
normal browsing, with its sandbox enabled.

## Current compatibility and stealth posture

- Chromiumoxide's latest published release is still 0.9.1. The recorded
  upstream base is that release. Upstream `main` is only five commits ahead as
  of the status date and has no merged CDP refresh.
- The first CAS-373 candidate keeps that controller base and its local patch
  queue while replacing only the generated bindings with the exact
  Chrome 153.0.8010.36 / `r1681091` protocol snapshot. Its source and generated
  digests are recorded in `crates/yosoi/src/internal/browser/vendor/chromiumoxide_cdp/VENDORING.md`.
- Upstream pull request 305 offers an unmerged M148-era CDP refresh. It is a
  candidate to inherit if the Yosoi surface reproduces the reported decode
  failure; it is not a current-Stable schema.
- Upstream pull request 331 adds session-aware out-of-process iframe support.
  It is a large, unmerged controller change and is not suitable for incidental
  adoption during a narrow baseline refresh.
- Yosoi's default stealth configuration does not use Chromiumoxide's broad
  page-world spoofing and does not disguise `navigator.webdriver`. CAS-374's
  supported non-zero loopback debug port makes Chrome report native `false`;
  explicit port zero retains native `true` for compatibility/diagnostics.
- The local minimal-CDP patch reduces eager Runtime, Network, Performance, Log,
  target auto-attach, and utility-world initialization. Those commands and
  their browser side effects may be observable; the age number of the Rust
  schema is not.
- The candidate removes the old default
  `--disable-features=IsolateOrigins,site-per-process` override and preserves
  Chrome's site/process isolation defaults. Cross-origin out-of-process frame
  support remains a separately tested controller capability; it must not be
  approximated by weakening the production browser's security boundary.
- CAS-383 adds a local Normal-mode controller path that associates nested flat
  sessions with the owning page, initializes child Page/Runtime state before
  resume, and routes frame-scoped Runtime/DOM/Accessibility commands through
  the frame's current session. It does not enable child-session Network capture.

CAS-383's focused out-of-cycle capability run used regular Stable Chrome
154.0.8037.57 in the hardened container, package SHA-256
`66c0645f6a19871bab2844b8537c11a0db2e7d3bea8ef85a1c7cb52a54e65a3e`
and executable SHA-256
`4d2512ae84986bf987e6ea8ef14ca1af555ae574fbaff5b5a8c78a8dd73fa36f`.
The process-swap, nested-frame, same-document navigation, transformed geometry,
trusted-input, Minimal-mode, and cleanup checks passed, and the identity-bound
profile completed 600/600 operations. This capability evidence does not by
itself replace the certified M153 tuple: a separate full compatibility,
security, native/headful/container, regression, and benchmark review is still
required before promoting M154 as the repository-wide browser baseline.

## First review decision

The first review selects Chrome 153.0.8010.36 / Chromium r1681091 as the
candidate to certify, while retaining Chromiumoxide 0.9.1 and rebasing only the
small Yosoi patch queue. Chromium 152.0.7977.82 is the comparison and rollback
browser. Chromium 154 is not a candidate because no regular Linux Stable build
exists at the review date.

This is a security-driven candidate, not a version-number preference. Google's
Chrome 153 Stable announcement lists 230 security fixes, including critical
WebGL and Cast memory-safety issues, and states that an exploit for
CVE-2026-87491 exists in the wild. The regular Linux package is pinned as
google-chrome-stable_153.0.8010.36-1_amd64.deb with SHA-256
9bb44e33031c2f2857cf36b4343051a12f93058e4b781e3c76313df87f6c8d32.

The matching protocol delta includes:

- removal of legacy Network interception types; Chromiumoxide now correlates
  active interception and authentication with Fetch.RequestId;
- new TargetInfo.parentId and tab embedderData topology;
- experimental Page.startScreenRecording and Page.stopScreenRecording;
- an experimental WebMCP domain for discovering and invoking page tools;
- Local Network Access and device-bound-session Network changes.

Accessibility and DOMSnapshot definitions are unchanged, so this upgrade does
not claim new accessibility capability. There is still no Canvas CDP domain;
canvas interaction remains a separate DOM/accessibility/runtime/visual/input
product idea. WebMCP, OOPIF support, and canvas understanding become follow-up
issues rather than being smuggled into this compatibility promotion.

An early pre-policy attempt briefly used Chrome for Testing 153.0.8010.36:

- archive SHA-256:
  167a098c4fdec156b58a9f678c90a84f9072d789f9c6e7b35496a6987b8b7ef8;
- executable SHA-256:
  79a4ebf6da53e4ceab11844257aabc5166f17b595dc694d6382cbee8ff50565f.

Those hashes exist only to identify and exclude the invalid artifact. None of
its results are certification or benchmark evidence, and Yosoi must not run it
again. All accepted regression, benchmark, native, headful, container, cleanup,
and evidence-integrity gates use the regular Stable package.

The complete repository-internal command/event audit is maintained in
[`chromium-cdp-surface.md`](chromium-cdp-surface.md). It records the M153
stability label, owning layer, purpose, and evidence for every active CDP
surface, plus dormant controller helpers. CAS-382 removes the public raw page,
target-id, and exact raw-ID attachment surfaces; see the surface document for
the forward-only migration note and the remaining limit around independently
managed CDP clients.

## Certified tuple and evidence

Decision: **Go**. Promote this exact compatibility tuple for Yosoi consumers:

| Identity | Certified value |
| --- | --- |
| Browser package | `google-chrome-stable_153.0.8010.36-1_amd64.deb` from Google's regular Stable Debian repository |
| Browser package SHA-256 | `9bb44e33031c2f2857cf36b4343051a12f93058e4b781e3c76313df87f6c8d32` |
| Browser executable SHA-256 | `ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db` |
| Chromium source identity | position `r1681091`, commit `507c6ee3e2f3b2ca0e660547e5b9ea4820c67f4c` |
| Chromiumoxide | 0.9.1; upstream base `a7e2bb835b9643410f9e3dc044f0d947e96cbfa4`; local source SHA-256 `46fe498185577066bff66c2814caba632159fbe3be3b68bf4da4e3cd5aa484ef` |
| Generated CDP | `chromiumoxide_cdp` `0.10.0-yosoi.m153.1`; Chrome 153.0.8010.36; Chromium `r1681091`; V8 `f343157cebb388bfa416baccb5d35507e6fe8cc7`; generated Rust SHA-256 `e5ef97c8087d679459f88af22761e9d048095bff1870ae414600617dcf0b41a8` |
| Container base | `sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a` |
| Certified container image | `sha256:90ef59e3973300ec7c0ef8d3d8d0ca7f791ca6cc485a34ce2f13041c001137fd` |
| Evidence source | JJ change `vsmsvvsozzyvuwmotlkwuqskxkppovxq`, snapshot commit `88d186bad8b5bd3cb3973bda541bcffb87388e9c`, source SHA-256 `0dacfd5f7e25e4aeb9d5229d0de5723e806f001b9abddeff78d39954cf8bae8f` |
| Platform/toolchain | Linux x86-64, kernel 7.2.3, Rust 1.98.0 |

The evidence snapshot predates only this final report and workspace-closeout
metadata. Browser/controller/CDP/runtime behavior is unchanged after that
snapshot. Local machine-readable evidence is retained under
`benchmarks/results/by-change/jj/vsmsvvsozzyvuwmotlkwuqskxkppovxq/`; the table
above is the repository source of truth for release identity.

Certification results:

- the complete workspace suite passed 1,074 tests with 3 explicitly skipped;
  full Clippy, formatting, source-size, dependency policy, shell syntax, and all
  54 PDL/generated-output hashes passed;
- native headless and isolated-Xvfb headful matrices each passed 12 cells and
  140 attempts with zero finalization failures, cleanup timeouts, or remaining
  processes;
- container headless and headful matrices each passed 12 cells and 140 attempts
  with complete cgroup disappearance, zero PID-limit events, and the exact
  regular Stable executable bound and verified before workload execution;
- the fixed 2-CPU/4-GiB/2048-PID container envelope peaked at 1,006 tasks and
  1,595,604,992 bytes headless, and 1,048 tasks and 1,690,230,784 bytes
  headful;
- CAS-352 passed the 1x1, 1x2, and 2x4 warm-process matrices from the integrated
  default workspace: 25, 50, and 100 attempts, zero exit failures, and no
  residual process, context, tab, sampled PID, or orphan PID after shutdown;
- the complete Rust benchmark classes passed: Criterion, Callgrind,
  allocation, process/perf, and Massif heap evidence. The paired CAS-377 to
  CAS-373 build/size harness recorded clean build time -4.882%, no-op build
  -0.693%, capture binary proxy -0.112%, and browser binary proxy +0.978%.
  No production binary exists, so the size values are explicitly proxies.

Older benchmark comparisons that crossed source and kernel revisions produced
review alerts in process, allocation, cache-miss, and heap metrics. They are not
accepted as causal Chrome regressions because the inputs were not equivalent;
the exact M153 evidence above becomes the comparison baseline for the next
monthly review. No correctness, cleanup, isolation, or unbounded-resource
regression was dismissed.

Consumer impact and follow-up:

- the generated CDP crate has an intentional forward-only 0.9-to-0.10 schema
  break; `Network.InterceptionId` is removed and active interception/auth flows
  use `Fetch.RequestId`;
- invalid CDP messages surface as typed compatibility failures; they are not
  silently ignored;
- regular Stable is mandatory. Chrome for Testing and other testing-only
  distributions fail closed at the runtime and certification boundaries;
- CAS-380 tracks typed renderer-crash CDP events, CAS-381 PDF runtime
  conformance, CAS-382 raw CDP boundary removal, CAS-383 session-aware OOPIF
  routing, CAS-378 canvas interaction, and CAS-379 WebMCP exploration.

Rollback is JJ change `xqkmkmvksypl` / commit
`5b784d2997be`, registry CDP 0.9.1 at `r1566079`, and native Chromium
152.0.7977.82 executable SHA-256
`78f94ee05d5d6fd1bd8239b9700d3cf54d540911febad4c7cea01080273943f9`.
It is an emergency comparison position, not a newly certified production tuple;
its browser is outside the preferred current-Stable target and must receive a
separate security decision before rollback deployment.

### Certified launch configuration

VoidCrawl disables Chromiumoxide's broad Puppeteer-derived default argument
set. For an ordinary launched session, it supplies exactly these stable
defaults in addition to Chromiumoxide's operational arguments:

```text
--remote-allow-origins=*
--disable-breakpad
--disable-dev-shm-usage
--no-first-run
--no-service-autorun
--no-default-browser-check
--no-pings
--password-store=basic
--disable-session-crashed-bubble
--disable-search-engine-choice-screen
--homepage=about:blank
--enable-gpu
--ignore-gpu-blocklist
--use-angle=vulkan
```

VoidCrawl now gives Chromiumoxide a reserved non-zero loopback debugging port;
explicit `BrowserDebugPortPolicy::ChromeAssigned` retains Chrome's
OS-assigned-port behavior for compatibility and diagnostic comparison.
Chromiumoxide adds the selected
`--remote-debugging-port`, `--disable-extensions`, and an ephemeral
`--user-data-dir`. Headless mode additionally uses
`--headless=new`, `--hide-scrollbars`, and `--mute-audio`; headful mode adds no
headless switch. The Chromium and GPU-process sandboxes remain enabled, site
and process isolation remain at Chrome defaults, and the launch timeout is 45
seconds unless the deployment environment explicitly overrides it. CAS-333
certification uses a separate 45-second browser cleanup deadline so the bounded
close, reap, kill, and handler-stop fallback phases can finish; a timeout or
remaining process still fails certification.
Native headful certification runs on a dedicated `1920x1080x24` X11/Xvfb
display rather than the operator's interactive compositor; the Xvfb executable
and wrapper digests are part of the recorded environment identity.
Ephemeral port/profile values are run-specific resources rather than stable
fingerprint inputs and are not persisted in evidence.

## Monthly currency review

Run this review on the first business day of every month and additionally when
Chrome publishes a security update, a new browser candidate is selected for
production, an upstream Chromiumoxide compatibility fix appears, or browser
conformance starts dropping or rejecting CDP messages. Monthly review is the
minimum cadence, not permission to defer a known security fix.

Record one row for each of the following:

1. latest regular Chrome/Chromium Stable version and release date;
2. exact certified native and container executable versions, source URLs or
   package identities, SHA-256 digests, and Chromium revisions;
3. browser lag in Stable milestones and calendar days;
4. latest Chromiumoxide release and upstream `main` revision;
5. vendored Chromiumoxide base revision and a named inventory of local patches;
6. `chromiumoxide_cdp`, `chromiumoxide_pdl`, and
   `chromiumoxide_types` package versions and lockfile checksums;
7. compiled CDP schema revision, mapped Chromium version, and lag in browser
   milestones;
8. open upstream CDP, target/session, timeout, cleanup, and OOPIF fixes relevant
   to Yosoi;
9. the exact launch-argument set and effective normal/minimal instrumentation;
10. focused headless/headful conformance and fingerprint results, each bound to
    the exact source and executable tuple.

Use these decision factors within the certification currency floor:

- relevant Chromium security fixes and known CVEs;
- browser and CDP compatibility with Yosoi's required surface;
- stability, correctness, cleanup, sandbox, and isolation behavior;
- useful new browser, CDP, accessibility, visual, canvas, or agentic features;
- measured browser and Rust performance/resource changes;
- Chromiumoxide patch and regeneration effort;
- availability of an exact reproducible browser artifact and rollback tuple.

Current regular Stable and its matching CDP revision are the production target;
the immediately previous major or a better patch release are natural comparison
and rollback candidates. A browser more than one Stable milestone or 30 days
behind is uncertified even if it remains a temporary rollback option. Within
that floor, there is no rule that a numerically newest patch must be promoted
when it is worse. Selecting an older eligible combination requires documented
security review, compatibility evidence, and a reason it is the most useful
low-effort choice. A relevant unpatched CVE, unexplained invalid CDP message,
or unsupported required feature can make remaining on it a no-go regardless of
its age.

The first review decision is **Go** for the exact certified tuple below. This
does not certify stealth; CAS-374 evaluates page-visible and network-visible
automation behavior against this now-fixed compatibility baseline.

## Supported and certified baseline policy

- **Optimization target:** choose the most current, secure, stable, capable, and
  low-maintenance Chromium/CDP combination supported by evidence. Version
  recency is a strong preference, not the only variable.
- **Certification target:** every evidence run names one exact executable and
  SHA-256 digest. Native and container certification use the same browser build
  where the platform permits it.
- **Candidate selection:** examine current Stable, its relevant patch releases,
  and the prior known-good major. Prefer the newest combination that satisfies
  the gates without disproportionate controller work.
- **Protocol selection:** prefer CDP definitions from the selected Chromium
  revision. A nearby older schema is acceptable when the required surface is
  proven compatible and it materially reduces maintenance. Do not tolerate
  unexplained decode loss or adopt tip-of-tree solely for freshness.
- **Pinning:** the selected Chromium artifact, CDP revision, Chromiumoxide
  upstream base, local patch revision, and container base are immutable inputs.
- **Experimental CDP:** every Yosoi-used experimental command, event, field, or
  enum has an explicit test against the certified browser.
- **Stealth:** evaluate commands, subscriptions, launch switches, page-world
  changes, and fingerprint consistency. Never use CDP schema age as a proxy for
  stealth evidence.
- **Security response:** a relevant CVE or missing security fix can force an
  out-of-cycle review and make the current baseline a no-go.

## Monthly go/no-go and release communication

The monthly review is both a release decision and a backlog-intake mechanism.
It recommends an upgrade; it does not silently modify production.

The ordinary upgrade path is intentionally boring:

1. **Change:** prepare the exact browser, CDP, controller, container, and source
   pin changes for the chosen candidate.
2. **Upgrade:** regenerate or update dependencies and make the smallest required
   compatibility changes.
3. **Benchmark:** run the complete Rust benchmark set and capture browser
   latency, allocations, peak RSS, build time, and binary size.
4. **Verify:** run the complete applicable regression suite plus headless,
   headful, cleanup, isolation, and fingerprint certification.
5. **Document:** record what changed, the go/no-go decision, compatible versions,
   consumer impact, rollback tuple, and every follow-up issue.

When a browser stack is promoted, pin one immutable release tuple:

- the regular Chrome/Chromium Stable artifact or package version, source, and
  SHA-256 digest;
- the container base-image digest and exact browser package installed inside
  it, with no floating `latest` or mutable local tag as certification evidence;
- the Chromiumoxide upstream commit plus the digest or revision of Yosoi's
  local patch queue;
- the exact `chromiumoxide_cdp`, `chromiumoxide_pdl`, and
  `chromiumoxide_types` versions, checksums, and PDL/Chromium revision;
- the Yosoi source revision, platform, launch configuration, and supported
  headless/headful modes.

The review makes one explicit recommendation:

- **Go:** promote the exact selected browser/CDP/controller tuple after all
  required correctness, isolation, cleanup, fingerprint, and regression gates
  pass.
- **No-go:** do not promote because a named gate failed. Record the owner,
  evidence, rollback position, and follow-up issue for every blocker.
- **Urgent remediation:** remaining on the current browser is unsafe or outside
  policy. Open a security/compatibility upgrade issue immediately, while still
  requiring the normal promotion evidence before declaring the new tuple
  certified.

Correctness, cleanup, sandboxing, isolation, secret safety, and bounded resource
behavior remain hard gates. Performance is evidence, not an automatic veto. If
a slowdown is attributable to the selected Chrome release and the security,
compatibility, or feature value is worthwhile, the review may explicitly accept
the regression and update the baseline. A slowdown caused by Yosoi, VoidCrawl,
the Chromiumoxide patch queue, or unbounded behavior must be investigated and
is not excused merely because Chrome also changed. The decision record states
which cost was accepted and why.

Every promoted Yosoi version has consumer-facing release notes containing:

1. previous and new Chromium, CDP schema, Chromiumoxide base, and Yosoi
   versions;
2. relevant Chromium security fixes, with authoritative advisory links and
   affected-version context;
3. new browser, CDP, accessibility, visual, canvas, and agentic capabilities
   that Yosoi now exposes or can investigate;
4. removed, deprecated, experimental, or behavior-changing protocol surfaces;
5. compatibility impact, required consumer action, and supported native and
   container environments;
6. measured correctness, performance, memory, binary-size, fingerprint, and
   cleanup changes, without claiming improvements that were not measured;
7. known limitations, rollback tuple, and linked follow-up issues.

Keep the authoritative compatibility matrix in this repository while the
external documentation site does not yet own it. At minimum it records each
Yosoi release, browser product/version/digest, CDP revision, Chromiumoxide base
and patch revision, supported platform and modes, certification date, and
support status. A future documentation-site migration must preserve a
repository-owned machine-readable release identity; do not create two
conflicting sources of truth.

### Backlog capture

Before completing a monthly review, classify every material finding as one of:

- security remediation;
- compatibility defect;
- breaking-change or consumer-migration work;
- controller/protocol investigation;
- performance or stability opportunity;
- new browser-product idea.

Create or link a deduplicated issue or sub-issue for each finding that should be
retained. Record why anything material was intentionally dismissed. Carry open
follow-ups into the next monthly review so discoveries do not disappear into a
report. WebMCP integration, canvas/visual interaction, accessibility semantics,
and proper OOPIF support are examples of new-idea or investigation tickets; they
are not bundled implicitly into a routine version promotion.

## Controller ownership decision

Keep Chromiumoxide as the controller and maintain a small auditable patch
queue. Do not write a replacement controller merely to make the dependency
number newer.

Retaining Chromiumoxide preserves tested transport, target/session routing,
timeouts, listener delivery, browser lifecycle, and cleanup behavior. The costs
are rebase work, an upstream release cadence slower than Chrome's, and the risk
that Yosoi-only patches become entangled with upstream changes. Reduce that
cost by recording each local patch's purpose and upstreamability, keeping
generated CDP bindings conceptually separate from controller logic, and
upstreaming generic fixes where practical.

Reconsider a Yosoi-owned controller only if measured evidence shows repeated
unfixable cleanup/session failures, required CDP capabilities cannot be adopted
through a bounded patch, upstream lag repeatedly blocks supported Stable
browsers, or maintaining the patch queue costs more than the controller surface
Yosoi actually uses. Stealth by itself is not a reason: any controller sends
CDP commands, and their effects—not the crate name—are what can be observed.

## CAS-373 certification sequence

1. Freeze the post-milestone-4 source revision.
2. Choose and hash the exact browser executable.
3. Inventory every Yosoi-used CDP command/event and mark its selected-schema
   status: stable, experimental, deprecated, removed, renamed, or newly
   required.
4. Exercise launch, attach, navigation, frame/target lifecycle, network,
   runtime diagnostics, accessibility, layout, screenshots, downloads,
   recording, context disposal, browser close, and crash/disconnect cleanup in
   headless and headful modes.
5. Investigate every invalid CDP message. Do not treat `ignore_invalid_messages`
   as compatibility evidence.
6. Run the complete applicable regression suite serially under the repository's
   resource-safety limits.
7. Run the complete Rust benchmark set and compare latency, allocations, peak
   RSS, clean/incremental build time, and release binary size with the prior
   exact baseline. Attribute browser regressions separately from Yosoi changes.
8. Publish the immutable source/controller/schema/browser/configuration tuple
   before starting CAS-374.

## Primary references

- [Chrome DevTools Protocol overview and versioning](https://chromedevtools.github.io/devtools-protocol/)
- [Chromium CDP compatibility policy](https://chromium.googlesource.com/chromium/src/+/HEAD/third_party/blink/public/devtools_protocol/README.md)
- [Chromiumoxide v0.9.1](https://github.com/mattsse/chromiumoxide/releases/tag/v0.9.1)
- [Chromiumoxide changes after the vendored base](https://github.com/mattsse/chromiumoxide/compare/a7e2bb835b9643410f9e3dc044f0d947e96cbfa4...main)
- [Chromiumoxide CDP refresh pull request 305](https://github.com/mattsse/chromiumoxide/pull/305)
- [Chromiumoxide OOPIF pull request 331](https://github.com/mattsse/chromiumoxide/pull/331)
- [Chrome 153 Stable and security fixes](https://chromereleases.googleblog.com/2026/09/stable-channel-update-for-desktop_0808145027.html)
- [Chrome 153 web-platform release notes](https://developer.chrome.com/release-notes/153)

## Runtime eligibility guard (2026-10-04)

VoidCrawl now rejects unknown, non-Stable, testing-only, and stale executable
identities before launch. `session/browser_distribution.rs` contains the
reviewed regular Linux Stable versions from [Google Version History](https://versionhistory.googleapis.com/v1/chrome/platforms/linux/channels/stable/versions/all/releases).
The newest reviewed milestone is 154; only exact Stable versions from milestones
153 and 154 are eligible. A superseded version expires 30 days after it stopped
serving, and the review snapshot itself expires after 30 days. Refresh this
eligibility list during monthly review and after relevant security updates.
Unknown releases fail closed. Eligibility does not promote M154 or replace the
M153 certification tuple; complete promotion evidence remains required.

Remote attachments now require a loopback debug endpoint, CDP SystemInfo's
absolute executable path, a successful local executable identity check, and
an exact match with Browser.getVersion. Both direct WebSocket URLs and resolved
HTTP endpoints undergo this validation. Nonlocal attachments and executable
identities outside the reviewed Linux Stable list are unsupported until a
verifiable distribution boundary is provided. CDP's product string alone
cannot distinguish regular Chrome from Chrome for Testing. Rejected attachments
disconnect without terminating the browser owned by the caller.

Generic arguments that disable browser/GPU sandboxing or site/process isolation
are rejected. The legacy `no_sandbox()` builder setting also returns an invalid
input error; there is currently no approved security-exception mechanism.
