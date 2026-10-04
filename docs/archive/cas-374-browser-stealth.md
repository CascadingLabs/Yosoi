# CAS-374 browser stealth policy and certification

Status: exact-source substrate certification complete. The accepted
compatibility input is CAS-373: regular Google Chrome Stable 153.0.8010.36,
Chromium `r1681091`, vendored Chromiumoxide 0.9.1 at upstream
`a7e2bb835b9643410f9e3dc044f0d947e96cbfa4`, and generated
`chromiumoxide_cdp 0.10.0-yosoi.m153.1`.

## Decision

Yosoi's stealth-certified profile is **coherent Chrome using its native
supported configuration plus minimal CDP**, not a page-patched anti-detect
browser:

- reserve a non-zero loopback debugging port so Chrome natively reports
  `navigator.webdriver=false` with its native property descriptor;
- remove only the `Headless` token from the real browser UA through the stable
  `Emulation.setUserAgentOverride` command;
- derive the Client Hints major version from that UA, the full version from
  `Browser.getVersion`, and the Linux platform version from the running kernel;
- keep the window, screen, viewport, device scale, platform, and languages
  mutually consistent;
- use the real Chrome plugin, permission, `window.chrome`, and WebGL surfaces;
- keep CSP, the Chromium sandbox, and site/process isolation enabled; and
- never enable Chromiumoxide's broad Puppeteer-derived page-world spoof bundle.

Minimal CDP is part of the certification result, not an optional optimization:
Device & Browser Info reported `isAutomatedWithCDP=true` and `isBot=true` for
normal CDP in both display modes, while both flags were `false` for minimal
CDP. Normal CDP remains a supported, explicitly selected capability profile
when a capture needs eager Runtime, Network, Performance, Log, or child-target
instrumentation; it is not the stealth-certified profile. The low-level
`BrowserSession` default remains normal because silently disabling those
capabilities would break known consumers.

The public `NavigatorWebdriverPolicy` currently has one supported variant,
`browser_reported`. Under the supported non-zero port configuration Chrome
reports native `false`; explicit port zero reports native `true`. Adding a
mutation policy requires a new typed variant and its own security,
compatibility, lifecycle, and detection evidence.

The old config-level custom `user_agent`, `use_builtin_stealth`, arbitrary
`inject_js`, and `bypass_csp` fields, plus the misleading `no_stealth`
builder, were removed. The ambiguous `.port(u16)` builder was replaced by the
typed `BrowserDebugPortPolicy::{SupportedEphemeral, ChromeAssigned, Fixed}`.
This is a forward-only internal API break. Explicit caller init scripts remain
possible through `Page::add_init_script`; they are not represented as a
supported stealth preset.

## Threat model

| Detector | Contract |
| --- | --- |
| Accidental automation disclosure | Avoid gratuitous flags, globals, stale UA versions, headless UA tokens, default 800x600 geometry, and internally inconsistent locale/platform/rendering values. |
| Commodity client-side checks | Measure the common webdriver, Chrome object, plugin, permission, frame, WebGL, UA, Client Hints, screen, and automation-global surfaces. Do not equate a green toy page with production anonymity. |
| Sophisticated fingerprinting | Record CDP instrumentation, worker/frame consistency, rendering, TLS/network limitations, and public-detector observations. Assume CDP and behavioral automation can remain detectable. |
| Security and isolation | Stealth never justifies disabling the browser/GPU sandbox, CSP, origin isolation, or site-per-process. Any future exception needs a separate typed and approved requirement. |

This ticket does not promise anti-bot bypass, solve challenges, or automate
access against a site's policy. Live pages are passive observations only.

## `navigator.webdriver` evaluation

The hermetic harness names and measures three policies:

| Policy | Mechanism | Result and disposition |
| --- | --- | --- |
| `supported_configuration` | Reserve a non-zero loopback debugging port, with no unsupported switch or JavaScript patch. Retry only when Chrome's launch stderr proves the release/bind race lost. | **Supported default.** Chrome 153 reports `false` with the native getter in both headless and headful modes. |
| `automation_disclosed` | Explicit `--remote-debugging-port=0`; no webdriver mutation. | Supported diagnostic/compatibility opt-in. Chrome reports `true` with the native getter across modes and lifecycle stages. |
| `bounded_disguise` | One pre-document getter returning `false`. | **Rejected for production.** It replaces the native getter, is page-world CDP mutation, must be repeated for every target/context, and remains distinguishable from browser-supported configuration. It exists only in the benchmark. |

`--disable-blink-features=AutomationControlled` is unsupported for this policy
and remains prohibited. Chromiumoxide's built-in stealth helper is also
rejected: it patches webdriver, permissions, plugins, WebGL, and
`window.chrome` with stale, detectable values.

## Hermetic contract

`profile_browser_stealth` serves a loopback-only page with a strict CSP and a
same-origin frame. Every cell records:

- `navigator.webdriver` and its getter source;
- UA, reduced and full Client Hints, platform, language, and languages;
- inner/outer/screen/available geometry, DPR, and color depth;
- WebGL masked and unmasked vendor/renderer;
- notification and Permissions API values;
- plugins, MIME type count, `window.chrome`, and common automation globals;
- CSP enforcement and frame parity; and
- first document, same-document navigation, cross-document navigation, new
  tab, isolated context, and attached existing-document behavior; and
- per-run elapsed time plus explicit isolated-context and browser cleanup
  completion.

The deterministic matrix runs the default `supported_configuration` policy in
headless/headful × normal/minimal CDP initialization, then compares the two
non-default webdriver candidates in both display modes under normal CDP. This
is eight cells; repeating rejected candidate policies under minimal CDP would
not add policy evidence. Live URLs are stored separately and cannot make a
hermetic failure pass.

Run the exact-baseline matrix serially:

```bash
cargo xtask benchmark browser-stealth
```

Add passive public observations explicitly:

```bash
scripts/browser/run-cas-374-browser-stealth.sh \
  --live-suite substrate
```

The substrate suite contains CreepJS, Device & Browser Info, Sannysoft, and
Incolumitas. It waits on detector DOM mutations rather than sleeping, retains
only bounded booleans/statuses/scores plus a body hash, and rejects URLs with
credentials, queries, fragments, or non-HTTPS schemes. Each target is observed
in headless/headful × normal/minimal CDP so reduced instrumentation is measured
as a capability trade rather than assumed to be stealthier.

Cloudflare's official Turnstile test keys are deterministic fixtures that
always pass/fail/force interaction; they verify integration but do not measure
Bot Management stealth. A meaningful Cloudflare result requires an authorized
owned zone with its challenge outcome or bot-score evidence. DataDome and
Kasada likewise have no suitable official public browser score page; testing
them requires an authorized protected path or vendor test account. CAS-374
must not probe arbitrary customer sites merely because a vendor protects them.

IP reputation, TLS fingerprints, mouse/keyboard behavior, and longitudinal
reputation remain explicitly outside this substrate slice.

The runner builds on the immutable CAS-373 image, verifies Chrome's exact
version and executable digest, runs as UID 10001 with the Chrome sandbox
required, drops all capabilities, enables `no-new-privileges`, uses the audited
Chrome seccomp profile, keeps a read-only root, and executes one bounded cell at
a time. It aborts before work if host swap already exceeds 4 GiB, or during
work if available memory falls below 8 GiB or swap grows by more than 128 MiB.
After explicit informed approval, `CAS374_ALLOW_HIGH_BASELINE_SWAP=1` records a
one-run exception to the starting-swap gate in the identity file.
`CAS374_MAX_SWAP_GROWTH_MIB` can raise the in-run growth ceiling from 128 MiB
to at most 1 GiB after explicit approval; the chosen bound is recorded in the
identity file and never relaxes the 8 GiB available-memory floor or per-cell
container limits. The runner also refuses to overlap another Cargo, rustc, or
Clippy process.

After a successful exact-source build, `--reuse-image` skips Cargo only when
the image's source hash and certified base label match the current workspace.

## Launch switch audit

VoidCrawl disables Chromiumoxide's broad default argument set. These are the
retained Yosoi defaults:

| Switch | Purpose and disposition | Security impact and evidence |
| --- | --- | --- |
| `--remote-allow-origins=*` | Chromiumoxide WebSocket interoperability. Retained. | Broadens DevTools Origin acceptance but not page origin isolation; debugging remains on an ephemeral loopback port and disposable profile. CAS-373 launch/attach and CAS-374 attached-view cells cover it. |
| `--disable-breakpad` | Avoid an unmanaged crash reporter process/artifact. Retained operationally. | Removes crash-upload behavior and some diagnostics; it does not suppress Chromium/CDP disconnect failure. CAS-373 crash/cleanup gates cover the current boundary. |
| `--disable-dev-shm-usage` | Avoid small `/dev/shm` failures in bounded containers. Retained. | Moves applicable shared-memory files to the bounded temporary filesystem; it can affect performance but does not disable a sandbox. CAS-333/CAS-373 container envelopes cover it. |
| `--no-first-run`, `--no-service-autorun`, `--no-default-browser-check`, `--disable-search-engine-choice-screen` | Suppress first-run UI and nondeterministic setup. Retained. | Removes setup UI/background variation without changing site or process isolation. Every CAS-374 lifecycle cell launches a new disposable profile. |
| `--no-pings` | Disable hyperlink-auditing side traffic. Retained for deterministic acquisition. | Intentionally changes optional audit-ping behavior and reduces unsolicited disclosure; navigation correctness remains covered by the browser suite. |
| `--password-store=basic` | Avoid desktop keyring prompts in ephemeral profiles. Retained. | The basic store is weaker than an OS keyring, so the default profile is disposable and must not persist credentials. Managed profiles remain an explicit separate boundary. |
| `--disable-session-crashed-bubble` | Suppress recovery UI for disposable profiles. Retained. | UI-only; typed crash/disconnect and cleanup evidence remain required. |
| `--homepage=about:blank` | Deterministic initial page. Retained. | No security default is weakened; stealth configuration is applied before the first real navigation. |
| `--enable-gpu`, `--ignore-gpu-blocklist`, `--use-angle=vulkan` | Request the host's real rendering path. Retained from the CAS-373 certified tuple. | `ignore-gpu-blocklist` can select a driver Chromium would otherwise avoid, so renderer identity, crashes, cleanup, and resources are hard gates and the GPU-process sandbox remains enabled. Native evidence reports the real AMD/Vulkan renderer; the container reports Mesa/llvmpipe and is kept as a separate population rather than spoofed. |

Chromiumoxide also adds the selected `--remote-debugging-port`,
`--disable-extensions`, an ephemeral `--user-data-dir`, and, in headless mode, `--headless=new`,
`--hide-scrollbars`, and `--mute-audio`. Port zero avoids a bind race but makes
Chrome report `navigator.webdriver=true`; it is now an explicit opt-in. The
default briefly reserves a non-zero loopback port and retries only a proven
bind collision, producing Chrome's native `false` value without disguise.
Disabling extensions prevents automation-extension residue and
reduces extension attack surface, at the cost of differing from extension-using
personal profiles. The ephemeral profile provides cleanup isolation. Headless,
scrollbar, and audio switches are mode behavior and are compared with headful
evidence. No default disables site/process isolation, CSP, the browser sandbox,
or the GPU sandbox.

The startup diagnostic stream must contain no unsupported-command-line warning
caused by Yosoi. Chrome's regular-Stable channel message is informational and
is not such a warning.

## Evidence interpretation

Hermetic pass/fail is authoritative for the stated coherence and lifecycle
contract. The public Device & Browser Info observation determines which CDP
mode is certified for stealth because CDP instrumentation is not observable to
the loopback fixture itself. Public detector
pages are mutable, can combine IP/TLS/behavioral reputation with JavaScript,
and may change without a Yosoi revision. Their raw result, URL, readiness
signal, detector booleans/rows, and body hash are evidence tied to the run—not
an acceptance oracle or a claim that a protected site will allow acquisition.

Container WebGL may report Mesa/llvmpipe while a native host reports its real
GPU. That difference is recorded rather than spoofed. Network/TLS and human
behavior are outside the hermetic fixture and must not be inferred from it.
