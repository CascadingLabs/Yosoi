# CAS-374 browser stealth results

Status date: 2026-09-24. The exact-source container matrix is complete.

## Decision

**GO** for the supported browser configuration with **minimal CDP** when
stealth is the priority. **NO-GO as a stealth profile** for normal CDP: it
remains a supported capability profile for captures that require eager Runtime,
Network, Performance, Log, or child-target instrumentation, but Device & Browser
Info detected that instrumentation in both headless and headful runs.

This is a substrate certification, not a universal anti-bot bypass claim.
Public detector pages are mutable observations. IP reputation, TLS fingerprint,
behavioral input, and longitudinal reputation were explicitly outside this
slice.

## Exact certified input

- JJ change `rkpzmnkvswzzqwyouvlzzwvolpuqlyzy`; its measured revision, source
  SHA-256, exact image ID, and probe binary identity are recorded together in
  the generated `identity.txt` rather than copied into this source-hashed file;
- certified CAS-373 base
  `sha256:90ef59e3973300ec7c0ef8d3d8d0ca7f791ca6cc485a34ce2f13041c001137fd`;
- regular Google Chrome Stable `153.0.8010.36`, executable SHA-256
  `ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db`;
- Chromiumoxide upstream base
  `a7e2bb835b9643410f9e3dc044f0d947e96cbfa4` plus the documented local patch
  queue;
- generated CDP `r1681091` / `chromiumoxide_cdp 0.10.0-yosoi.m153.1`;
- sandbox required, site/process isolation at Chrome defaults, all Linux
  capabilities dropped, `no-new-privileges`, audited seccomp profile, read-only
  root, and one 1-CPU/2-GiB cell at a time.

The evidence is stored under the ignored local benchmark result directory:

```text
benchmarks/results/by-change/jj/rkpzmnkvswzzqwyouvlzzwvolpuqlyzy/browser/cas-374-stealth
```

## Hermetic certification

All eight deterministic cells passed with zero contract violations and complete
browser/context cleanup:

| Display | Webdriver policy | CDP | Native value | Result |
| --- | --- | --- | --- | --- |
| headless | supported configuration | normal | `false` | pass |
| headless | supported configuration | minimal | `false` | pass |
| headful | supported configuration | normal | `false` | pass |
| headful | supported configuration | minimal | `false` | pass |
| headless | automation disclosed | normal | `true` | diagnostic pass |
| headful | automation disclosed | normal | `true` | diagnostic pass |
| headless | bounded disguise | normal | `false`, mutated getter | rejection evidence collected |
| headful | bounded disguise | normal | `false`, mutated getter | rejection evidence collected |

The supported configuration uses a reserved non-zero loopback debugging port.
Chrome reports `navigator.webdriver=false` through its native getter; Yosoi does
not patch the property. Explicit Chrome-assigned port zero is the typed
automation-disclosed comparison and natively reports `true`. The JavaScript
getter disguise remains rejected because its non-native getter is itself
distinguishable.

Every supported cell passed the following coherence checks across the first
document, same-document navigation, cross-document navigation, a new tab, an
isolated context, a same-origin frame, and a second controller attached to the
existing page:

- no headless token in the UA and exact Chrome 153 full-version Client Hints;
- main document, frame, and dedicated Worker agree on UA, platform, languages,
  hardware concurrency, device memory, brands, full version, and platform
  version;
- HTTP UA, Accept-Language, and Client Hint headers agree with JavaScript;
- `1920x1080` viewport/screen geometry, native plugins and permissions, real
  WebGL identity, and strict CSP enforcement;
- no common Selenium, Puppeteer, or Playwright globals; and
- attached-controller adoption and cleanup complete without creating another
  tab.

The container truthfully reported Mesa/llvmpipe. It was not spoofed as a
physical GPU.

## Public substrate observations

All 16 public observations reached their detector-specific readiness signal.
These results are tied to the exact run above and are not acceptance gates.

### Device & Browser Info

This detector produced the decisive CDP result:

| Display | CDP | `isBot` | `isAutomatedWithCDP` | Other captured flags |
| --- | --- | --- | --- | --- |
| headless | minimal | `false` | `false` | all `false` |
| headful | minimal | `false` | `false` | all `false` |
| headless | normal | `true` | `true` | all `false` |
| headful | normal | `true` | `true` | all `false` |

The other captured flags include webdriver in the main page/frame, Playwright,
headless Chrome, bot UA, Client Hint inconsistency, Worker inconsistency,
Chrome-object inconsistency, WebGL inconsistency, iframe override, suspicious
weak signals, and excessive hardware concurrency. This is why normal CDP is
not certified as the stealth profile even though its browser fingerprint is
internally coherent.

### Sannysoft

Headless/headful and normal/minimal all reported the selected automation rows
as passing:

- WebDriver New: `missing (passed)`;
- WebDriver Advanced: `passed`;
- Chrome New: `present (passed)`; and
- Plugins: `PluginArray`, `passed`.

### Incolumitas

Every mode reported `OK` for `puppeteerEvaluationScript`, `webdriverPresent`,
`connectionRTT`, `refMatch`, and `overrideTest`.

### CreepJS

| Display | Normal | Minimal |
| --- | --- | --- |
| headless | headless 33%, like-headless 50%, stealth 0% | headless 33%, like-headless 50%, stealth 0% |
| headful | headless 0%, like-headless 44%, stealth 0% | headless 0%, like-headless 44%, stealth 0% |

Minimal CDP did not change these CreepJS scores. Headless remains observable as
headless on some surfaces; that fact is retained rather than hidden behind a
spoof.

## Defect found and fixed during certification

Adding a real Worker to the fingerprint fixture exposed a race in the vendored
Chromiumoxide attach path. `Target.getTargets` could create and attach a second
controller target while the same target's discovery event was already being
initialized. The second controller then timed out adopting the page.

Target creation is now idempotent and the redundant raw attach is removed. A
focused real-browser regression keeps a Worker active while a second CDP client
adopts and evaluates the existing page. That regression passes, and the final
24-cell matrix completed on the fixed controller.

## Validation

- exact-source release image build: pass;
- eight hermetic browser cells: pass, zero violations;
- 16 approved public observations: complete;
- active-Worker attached-controller regression: 1 passed;
- focused VoidCrawl and probe compile: pass;
- exact Chrome/controller/CDP/base/image/probe identities: recorded;
- Rust formatting and runner shell syntax: pass; and
- browser/context cleanup: pass in every published cell.

## Explicit limits

Cloudflare Turnstile's public test keys are deterministic integration fixtures,
not a stealth score. A meaningful Cloudflare Bot Management result needs an
authorized owned zone and its challenge or bot-score evidence. DataDome and
Kasada likewise require an authorized protected target or vendor test account;
CAS-374 did not probe arbitrary customer sites.

Normal CDP remains necessary when a capture requires the instrumentation that
minimal mode deliberately omits. Callers must choose that capability trade
explicitly and must not describe a normal-CDP result as stealth-certified.
