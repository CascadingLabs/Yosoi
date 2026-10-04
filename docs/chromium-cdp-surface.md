# Yosoi CDP surface at Chromium M153

Protocol inventory status date: 2026-09-15. API boundary update: 2026-09-24
(CAS-382). This is the CAS-373 source inventory for the exact
Chrome 153.0.8010.36 / Chromium `r1681091` PDL checked into
`vendor/chromiumoxide_cdp/pdl`. It describes repository-internal traffic, not
every definition generated into `chromiumoxide_cdp`.

## Scope and status vocabulary

The inventory includes commands constructed by `void_crawl_core`, commands
issued automatically by the vendored Chromiumoxide controller on a VoidCrawl
path, and events explicitly consumed or subscribed by either layer. A
conditional path still counts: for example, authentication, full-CDP mode,
screenshots, downloads, and recording are part of the surface even when a
particular capture does not use them.

It excludes Chromiumoxide convenience methods that have no VoidCrawl caller.
Those references are listed separately so they cannot be mistaken for browser
traffic. VoidCrawl does not expose a raw Chromiumoxide page, `SessionId`, or
`TargetId`; downstream users cannot expand this inventory through a returned
controller handle. Independently managed clients that connect through a
browser WebSocket endpoint may issue their own CDP commands, which are outside
this repository's traffic inventory.

## Forward-only VoidCrawl API migration

`Page::inner()` and the raw-ID `BrowserSession::attach_page` operation have
been removed, and `Page::target_id()` is now crate-private. Use typed VoidCrawl
operations for browser work; an attached `BrowserSession` can enumerate its
typed pages without exposing their controller identities. No compatibility
alias preserves the old accessors. The source audit found six internal
active-navigation calls to `Page::inner()` and one conformance-test call that
sent `CrashParams`. The six internal calls now use `Page::cdp()`; CAS-382
removed the conformance case for CAS-380's typed replacement. No VoidCrawl
example or external-consumer documentation claimed arbitrary raw CDP access.
The prior `Page::target_id()` docs advertised exact cross-process adoption;
that raw-ID workflow is intentionally retired.

Statuses below are read from the exact M153 PDL:

- **stable**: the domain member has neither `experimental` nor `deprecated`.
- **experimental** or **deprecated**: the PDL marks the member that way.
- **stable; experimental field**: the command/event is stable, but Yosoi uses
  a field or result type that the PDL marks experimental.
- **removed -> newly required**: an old identity no longer exists and the
  controller must use the named M153 replacement.
- **renamed**: reserved for an M153 rename. No active Yosoi command or event
  was found in this category.

“Stable” is a schema label, not a claim that a behavior has been certified on
every runtime. Conversely, an experimental label does not mean the path is
untested.

## Domain inventory

| Domain | M153 domain status | Yosoi ownership and use |
| --- | --- | --- |
| Accessibility | experimental | VoidCrawl accessibility snapshots and role/name location. |
| Browser | stable | Version/window inspection, permissions, download routing, and graceful browser close. `BrowserContextID` and several used commands remain experimental. |
| DOM | stable | Document/node resolution and layout geometry. |
| Emulation | stable | Viewport, media, locale, timezone, geolocation, UA/client-hint, touch, and screenshot background overrides. |
| Fetch | stable | Chromiumoxide request interception and HTTP authentication. |
| Input | stable | Trusted mouse and keyboard dispatch. |
| Log | stable | Chromiumoxide enables the domain in normal mode; VoidCrawl has no retained Log event stream. |
| Network | stable | Request lifecycle, response bodies, headers, cookies, cache policy, and optional offline mode. |
| Page | stable | Page/frame lifecycle, navigation, layout, PDF, screenshots, and screencast recording. |
| Performance | stable | Chromiumoxide enables the domain in normal mode; VoidCrawl does not currently request metrics. |
| Runtime | stable | JavaScript evaluation, execution contexts, console, and exceptions. |
| Security | stable | Optional certificate-error override during controller initialization. |
| Target | stable | Discovery, creation, flat-session attachment, context disposal, focus, and target lifecycle. |

Generated but not used by a repository-internal path: experimental
`DOMSnapshot`, experimental `Inspector`, experimental `Storage`, and
experimental `WebMCP`. `Debugger` and `CSS` are stable domains with dormant
vendored convenience methods only. In particular, rendered-DOM capture uses
`Runtime.evaluate`; it does not use `DOMSnapshot`.

## Active commands

### Browser and target control

| CDP command | M153 status | Purpose | Owner layer | Test/evidence |
| --- | --- | --- | --- | --- |
| `Browser.getVersion` | stable | Record the connected renderer/product and protocol-facing version data. | Both | `integration::test_launch_and_version`; `environment_snapshot`; exact PDL. |
| `Browser.getWindowForTarget` | experimental | Determine whether a page has a window to itself before non-foreground recording. | VoidCrawl | `recording::foreground_is_auto_detected_from_window_placement`; exact PDL. |
| `Browser.setPermission` | experimental | Grant geolocation in the page's retained browser context. | VoidCrawl | `context_isolation::independent_contexts_isolate_permissions_headers_and_renderer_state`; exact PDL. |
| `Browser.setDownloadBehavior` | experimental | Route a download to a bounded caller directory, then reset to `default`. | VoidCrawl | `download`, `download_events`; exact PDL. |
| `Browser.close` | stable | Gracefully close a launched browser before bounded process reap/kill fallback. | Both | `context_isolation::session_close_before_reaps_the_launched_browser` and `cancelling_session_close_can_be_retried`. |
| `Target.setDiscoverTargets` | stable | Subscribe to browser-wide target lifecycle in normal mode; deliberately omitted in minimal mode. | Chromiumoxide | `cdp_minimal`; `integration::test_attached_pages_include_preexisting_tab`. |
| `Target.getTargets` | stable | Discover pre-existing attached tabs and compare page/window placement. | Both | `integration::test_attached_pages_include_preexisting_tab`; recording window tests. |
| `Target.createBrowserContext` | stable; experimental field/type | Create a disposable context. Yosoi uses experimental `disposeOnDetach`; the returned `BrowserContextID` type is experimental. | VoidCrawl | `context_isolation`. |
| `Target.disposeBrowserContext` | stable; experimental type | Delete every page and mutable state family in an isolated context. | VoidCrawl | context cancellation, drop, and explicit-disposal tests in `context_isolation`. |
| `Target.createTarget` | stable; experimental field/type | Create a blank tab, a context-bound tab, or a separate-window tab. `browserContextId` is experimental. | Both | `integration`, `context_isolation`, and recording own-window tests. |
| `Target.attachToTarget` | stable | Establish a flat target session for a new or adopted page. | Chromiumoxide | attached-page integration coverage and controller tests. |
| `Target.detachFromTarget` | stable | Detach auto-attached service-worker sessions. The old optional `targetId` parameter is deprecated; Yosoi uses `sessionId`. | Chromiumoxide | controller source inspection; browser acquisition service-worker coverage. |
| `Target.closeTarget` | stable; deprecated result field | Close a target whose initialization failed. Yosoi does not read deprecated `success`. | Chromiumoxide | controller initialization-failure path inspection. |
| `Target.setAutoAttach` | stable; experimental field | Auto-attach related targets in normal mode. Yosoi uses experimental `flatten`; minimal mode omits this command. | Chromiumoxide | `cdp_minimal`; controller source inspection. |
| `Target.activateTarget` | stable | Focus a target before headless screenshot composition. | Chromiumoxide | screenshot integration and visual-snapshot tests. |

Launch itself is not a CDP command: Chromiumoxide spawns the configured
executable and reads the `DevTools listening on ...` WebSocket URL. Remote
attach accepts a WebSocket URL directly or resolves `/json/version` over HTTP,
then opens the same CDP WebSocket transport. The commands above begin only
after that connection exists.

### Page, frame, layout, screenshot, PDF, and recording

| CDP command | M153 status | Purpose | Owner layer | Test/evidence |
| --- | --- | --- | --- | --- |
| `Page.enable` | stable | Enable page lifecycle/frame notifications during target initialization. | Chromiumoxide | controller source; `cdp_minimal`; integration/navigation suites. |
| `Page.getFrameTree` | stable | Seed and re-read frame/document identity. | Both | active-navigation, frame, document-snapshot, and conformance tests. |
| `Page.setLifecycleEventsEnabled` | stable | Emit named lifecycle events used by navigation accounting. | Chromiumoxide | active-navigation and acquisition-conformance tests. |
| `Page.addScriptToEvaluateOnNewDocument` | stable | Create the utility-world bootstrap in normal mode and install explicit caller init scripts. The supported stealth preset installs none; CAS-374 uses one only to measure the rejected bounded-disguise policy. | Both | vendored page tests; CAS-374 hermetic evidence. |
| `Page.createIsolatedWorld` | stable | Create Chromiumoxide's per-frame utility world in normal mode. | Chromiumoxide | controller source and frame-evaluation coverage. |
| `Page.navigate` | stable | Start tracked or raw navigation. | Both | `active_navigation`, `navigation_capture`, and `integration::test_navigate`. |
| `Page.stopLoading` | stable | Bound cancellation/deadline cleanup for in-flight navigation. | VoidCrawl | active-navigation cancellation/deadline coverage. |
| `Page.close` | stable | Close one tab and run its before-unload behavior. | VoidCrawl via Chromiumoxide | active-navigation page-close coverage and isolated-page cleanup. |
| `Page.bringToFront` | stable | Keep a screencast page painting, and explicitly foreground screenshots in known-required paths. | VoidCrawl | recording foreground/shared-window tests and screenshot integration. |
| `Page.setBypassCSP` | stable | Dormant Chromiumoxide helper only. VoidCrawl no longer exposes it through stealth configuration. | Chromiumoxide | source audit; CAS-374 strict-CSP fixture. |
| `Page.getLayoutMetrics` | stable | Capture CSS layout/visual/content coordinate spaces. Yosoi reads `css*` results, not the deprecated device-pixel result fields. | Both | `visual_snapshot::layout_snapshot_reports_css_coordinate_spaces`; screenshot/selector tests. |
| `Page.captureScreenshot` | stable; experimental field | Capture PNG bytes/regions/full page. Region capture uses experimental `captureBeyondViewport`. | Both | integration screenshot cases, `visual_snapshot`, `selector_bbox`. |
| `Page.printToPDF` | stable | Produce PDF bytes from the current page. | VoidCrawl via Chromiumoxide | `browser_acquisition_conformance::pdf_bytes_returns_bounded_pdf_and_typed_error_for_closed_page`; loopback fixture, bounded PDF structure, and typed closed-page failure. |
| `Page.startScreencast` | experimental | Start the existing JPEG/PNG screencast-frame recording path. | VoidCrawl | `recording`. |
| `Page.screencastFrameAck` | experimental | Acknowledge every accepted screencast frame. | VoidCrawl | recording frame/partial-failure coverage. |
| `Page.stopScreencast` | experimental | Stop recording on success, cancellation, drop, or partial failure. | VoidCrawl | `recording` and recording partial-failure tests. |

M153 also defines experimental `Page.startScreenRecording` and
`Page.stopScreenRecording`. They are **new but not used**. Yosoi recording
continues to use the older experimental screencast trio above; no capability,
performance, or compatibility claim is made for the new recording commands.

### Runtime, DOM, accessibility, and input

| CDP command | M153 status | Purpose | Owner layer | Test/evidence |
| --- | --- | --- | --- | --- |
| `Runtime.enable` | stable | Receive execution-context/console/exception events in normal mode or lazily when requested; omitted from minimal initialization. | Both | `cdp_minimal`; observation and environment tests. |
| `Runtime.evaluate` | stable | Environment, DOM, selector, scroll, download-driver, and arbitrary expression evaluation. | Both | integration evaluation, document snapshot, selector, download, and conformance tests. |
| `Runtime.callFunctionOn` | stable | Evaluate functions in a selected execution context or against a resolved node. | Both | frame evaluation, element interaction, and AX click coverage. |
| `Runtime.runIfWaitingForDebugger` | stable | Resume a target paused by normal-mode auto-attach. | Chromiumoxide | controller source and child-target/browser acquisition coverage. |
| `DOM.getDocument` | stable | Obtain the root node before selector or AX-root resolution. | Both | integration selector and AX tests. |
| `DOM.querySelector` | stable | Resolve the first CSS element for Chromiumoxide element interaction. | Chromiumoxide | `integration::test_query_selector`; selector and input tests. |
| `DOM.describeNode` | stable | Map frontend node identity to backend node identity. | Chromiumoxide | element/selector interaction tests. |
| `DOM.resolveNode` | stable | Resolve a backend DOM node to a Runtime object. | Both | selector/AX interaction tests. |
| `DOM.getBoxModel` | stable | Obtain content geometry for role/selector targeting. | Both | `selector_bbox`, `ax_tree`. |
| `DOM.getContentQuads` | experimental | Pick a visible clickable point for Chromiumoxide element clicks. | Chromiumoxide | element-click integration and AX/selector click tests. |
| `Accessibility.getFullAXTree` | experimental (domain and command) | Capture a bounded full AX tree, including frame-scoped capture. | VoidCrawl | `ax_tree`, document snapshot, browser conformance. |
| `Accessibility.queryAXTree` | experimental (domain and command) | Resolve role/name matches against an AX subtree. | VoidCrawl | `ax_tree::query_ax_tree_matches_by_role_and_name` and role selector tests. |
| `Input.dispatchMouseEvent` | stable | Trusted mouse movement, press/release, wheel, and humanized pointer input. | Both | AX click and input/selector tests. |
| `Input.dispatchKeyEvent` | stable | Trusted keyboard input and Chromiumoxide typing. | Both | integration interaction coverage. |

### Network, Fetch, cookies, and emulation

| CDP command | M153 status | Purpose | Owner layer | Test/evidence |
| --- | --- | --- | --- | --- |
| `Network.enable` | stable | Enable request/response lifecycle events in normal mode or lazily for capture. | Both | `cdp_minimal`, navigation/response capture, observation. |
| `Network.setCacheDisabled` | stable | Honor configured cache policy and interception requirements. | Chromiumoxide | cache provenance and context-isolation tests. |
| `Network.setExtraHTTPHeaders` | stable | Install page-scoped request headers after Network is enabled. | Both | `integration::test_set_headers`; context header isolation. |
| `Network.setUserAgentOverride` | stable | Apply the UA-only override used by Chromiumoxide's optional built-in stealth helper. The command redirects to Emulation in M153; this path does not set the experimental metadata field. | Chromiumoxide | custom-stealth integration coverage and source inspection. |
| `Network.getResponseBody` | stable | Capture a completed response body by Network request id. | VoidCrawl | navigation and passive-response capture tests. |
| `Network.getCookies` | stable | Read cookies matching the page URL. | VoidCrawl via Chromiumoxide | cookie/context isolation tests. |
| `Network.setCookies` | stable | Set one or more page cookies. | VoidCrawl via Chromiumoxide | cookie/context isolation tests. |
| `Network.deleteCookies` | stable | Remove page cookies before replacement or explicit deletion. | VoidCrawl via Chromiumoxide | cookie/context isolation tests. |
| `Fetch.enable` / `Fetch.disable` | stable | Turn interception/authentication pausing on or off. | Chromiumoxide | Fetch authentication cleanup regression and controller tests. |
| `Fetch.continueRequest` | stable | Resume a paused request when only protocol-level interception is needed. | Chromiumoxide | controller interception tests/source. |
| `Fetch.continueWithAuth` | stable | Answer an authentication challenge and clear attempt state at request terminal events. | Chromiumoxide | Fetch authentication cleanup regression. |
| `Security.setIgnoreCertificateErrors` | stable | Preserve configured bad-TLS behavior, including minimal mode. | Chromiumoxide | `cdp_minimal::minimal_network_init_preserves_ignore_https_without_network_enable`. |
| `Emulation.setDeviceMetricsOverride` | stable | Apply persistent or one-shot viewport/device metrics, including coherent screen dimensions and position. | Both | viewport, screenshot restoration, and CAS-374 fingerprint tests. |
| `Emulation.clearDeviceMetricsOverride` | stable | Clear a viewport override. The deprecated redirected `Page` command is not used. | Both | `integration::clear_viewport_removes_the_override`. |
| `Emulation.setTouchEmulationEnabled` | stable | Keep touch capability aligned with the effective viewport. | Both | viewport integration coverage. |
| `Emulation.setDefaultBackgroundColorOverride` | stable | Make screenshot backgrounds transparent and restore afterward when requested. | Chromiumoxide | screenshot omit-background path/source. |
| `Emulation.setEmulatedMedia` | stable | Apply color-scheme and reduced-motion media preferences. | VoidCrawl | environment/rendering preference tests. |
| `Emulation.setGeolocationOverride` | stable | Apply coordinates after context-scoped permission grant. | VoidCrawl | context-isolation permission tests. |
| `Emulation.setLocaleOverride` | experimental | Override the JavaScript locale. | VoidCrawl | environment/emulation tests. |
| `Emulation.setTimezoneOverride` | stable | Override the renderer timezone. | VoidCrawl | environment/emulation tests. |
| `Emulation.setUserAgentOverride` | stable; experimental field | Remove only the headless UA token while keeping UA, exact browser version, platform, language, and Client Hints coherent. Yosoi sets experimental `userAgentMetadata`. | VoidCrawl | CAS-374 lifecycle matrix and viewport integration coverage. |
| `Performance.enable` | stable | Normal-mode Chromiumoxide initialization; no metrics are retained by VoidCrawl. | Chromiumoxide | `cdp_minimal` and source inspection. |
| `Log.enable` | stable | Normal-mode Chromiumoxide initialization; no Log event stream is retained by VoidCrawl. | Chromiumoxide | `cdp_minimal` and source inspection. |

## Active events

| CDP event | M153 status | Purpose | Owner layer | Test/evidence |
| --- | --- | --- | --- | --- |
| `Target.targetCreated` / `Target.targetDestroyed` | stable | Add/remove tracked targets in normal discovery mode. | Chromiumoxide | attach/page/context tests. |
| `Target.targetCrashed` | stable | In normal mode, correlate a discovered crashed target internally and wake only its owned page's sticky crash signal; no raw target/session identifier is added to VoidCrawl errors. | Chromiumoxide; observed by VoidCrawl | `handler::target::renderer_crash_tests`; `observation::renderer_crash_progress_is_terminal`; renderer-failure mapping test. |
| `Target.attachedToTarget` / `Target.detachedFromTarget` | experimental | Bind/unbind flat sessions and resume or detach auto-attached child targets. | Chromiumoxide | attach and child-target paths. |
| `Page.frameAttached` / `Page.frameDetached` / `Page.frameNavigated` | stable | Maintain the frame tree and document generations. | Chromiumoxide; observed by VoidCrawl | active-navigation, document identity, frame conformance. |
| `Page.navigatedWithinDocument` | experimental | Type same-document navigation separately from a new loader. | Both | `active_navigation::same_document_navigation_is_explicitly_typed`. |
| `Page.frameStartedLoading` / `Page.frameStoppedLoading` | experimental | Reset frame load state and provide explicit active-navigation progress/termination. | Both | active-navigation tests. |
| `Page.lifecycleEvent` | stable | Track loader `init`, DOM content, load, network-idle, and ordered navigation progress. | Both | active-navigation, observation, and navigation capture. |
| `Page.screencastFrame` | experimental | Deliver encoded frames and session ids for acknowledgment. | VoidCrawl | recording tests. |
| `Network.requestWillBeSent` | stable | Record request start, redirects, document identity, and endpoint provenance. | Both | navigation capture, observation, response capture. |
| `Network.responseReceived` | stable | Record response metadata and match awaited responses. | Both | navigation/response capture and observation. |
| `Network.loadingFinished` / `Network.loadingFailed` | stable | Mark terminal request state and trigger body capture or explicit failure. | Both | navigation/response capture and observation. |
| `Network.requestServedFromCache` | stable | Mark Chromiumoxide request cache provenance. | Chromiumoxide | cache-provenance coverage. |
| `Fetch.requestPaused` / `Fetch.authRequired` | stable | Correlate paused requests and drive request/auth continuation. | Chromiumoxide | Fetch authentication cleanup regression. |
| `Runtime.executionContextCreated` / `Runtime.executionContextDestroyed` / `Runtime.executionContextsCleared` | stable | Maintain frame-to-main/utility-world execution-context identity. | Chromiumoxide; creation also observed by VoidCrawl | frame evaluation and environment readiness coverage. |
| `Runtime.consoleAPICalled` / `Runtime.exceptionThrown` | stable | Produce bounded, secret-safe runtime diagnostics. | VoidCrawl | observation and acquisition conformance. |
| `Runtime.bindingCalled` | experimental | Chromiumoxide has an explicit handler, but VoidCrawl installs no Runtime binding today. | Chromiumoxide dormant receive path | source inspection only. |

## M153 removals, replacements, and newly present surfaces

| Surface | M153 status | Yosoi consequence | Evidence |
| --- | --- | --- | --- |
| `Network.InterceptionId` | removed -> `Fetch.RequestId` newly required | The M145-era generated identity is absent from the exact M153 PDL. Chromiumoxide now stores Fetch request ids, correlates them to `Network.RequestId`, and uses the Fetch id for authentication cleanup and continuation. Do not recreate a fake Network type. | Absence from all 54 M153 PDL inputs; `vendor/chromiumoxide/src/handler/network.rs` and `handler/http.rs`; Fetch cleanup regression. |
| `TargetInfo.parentId` | newly present stable field | The generated target shape accepts the M153 tab/iframe parent topology. | `chromiumoxide_cdp::m153::target_info_accepts_m153_parent_and_embedder_metadata`. |
| `TargetInfo.embedderData` | newly present experimental field | The generated target shape accepts M153 tab embedder metadata; Yosoi stores but does not interpret it. | Same M153 contract test. |
| `Page.startScreenRecording` / `Page.stopScreenRecording` | newly present experimental commands; not used | No change to Yosoi recording; adoption requires a separate typed implementation and measurement against the screencast path. | Exact `Page.pdl`; no production symbol reference. |
| `WebMCP` | newly present experimental domain; not used | No command, event, generated type, or page tool is called by VoidCrawl or Chromiumoxide. It remains follow-up product work, not part of CAS-373 compatibility certification. | Exact `WebMCP.pdl`; production source search has no match. |

No active Yosoi command or event was renamed in the M153 snapshot. The material
breaking change found by the controller compile/audit was the removed Network
interception identity above.

## Downloads, browser close, crash, and disconnect semantics

- Downloads use experimental `Browser.setDownloadBehavior`, then wait on
  `notify` filesystem events and inspect completed files. Yosoi does **not**
  subscribe to experimental `Browser.downloadWillBegin` or
  `Browser.downloadProgress`; the deprecated Page versions are also unused.
- Isolated cleanup uses stable `Target.disposeBrowserContext`. Page cleanup uses
  stable `Page.close`. A launched-session close uses stable `Browser.close`,
  then bounded process wait/kill/reap. An attached-session close deliberately
  sends no browser-close command; it stops the local handler/connection only.
- Browser-process crash and WebSocket disconnect are detected when the
  Chromiumoxide handler stream ends. Owned event streams then close and
  VoidCrawl reports `ProviderDisconnected`/`BrowserClosed` as appropriate.
- The stable `Target.targetCrashed` event is correlated against Chromiumoxide's
  discovered targets in Chromiumoxide's owned target map and delivered as a
  sticky, page-scoped signal. The direct and managed capture paths both report
  `voidcrawl.renderer.crashed` and map it to
  `BrowserProviderStop::RendererFailure` in normal CDP mode. Minimal mode
  deliberately omits `Target.setDiscoverTargets`, so the stable event is not
  delivered there; renderer crashes remain bounded by the deadline or a
  disconnect signal. Ordinary close, detach, cancellation, disconnect, and
  deadline remain separate outcomes. The experimental `Inspector.targetCrashed`
  and `Inspector.detached` events are unused.
- The certified regular-Stable harness did not receive `Target.targetCrashed`
  from the synthetic `Page.crash` command. Chromium's own `Page.crash`
  browser test is disabled as flaky upstream. CAS-380 therefore has
  deterministic controller correlation, sticky-signal, observation-terminal,
  and Yosoi mapping coverage, but does not claim an end-to-end synthetic crash
  certification. A real crash that fails to emit the stable event remains an
  out-of-cycle compatibility finding and is still bounded by the attempt
  deadline.

## Dormant vendored references

These commands exist in compiled Chromiumoxide methods but have no current
repository-internal VoidCrawl caller: DOM/CSS/Debugger enable/disable,
`DOM.querySelectorAll`, experimental `DOM.performSearch`, experimental
`DOM.getSearchResults`, experimental `DOM.discardSearchResults`,
`Runtime.addBinding`, `Runtime.disable`, `Runtime.getProperties`,
`Debugger.getScriptSource`, `Page.reload`, and `Performance.getMetrics`.
Browser-level experimental `Storage` cookie helpers are also dormant;
VoidCrawl page cookies use the stable Network commands listed above.

Deprecated `Network.emulateNetworkConditions` is a special dormant case: it is
the one deliberately generated deprecated definition and remains a maintained
Chromiumoxide compile surface, but VoidCrawl has no caller. The exact status is
covered by the narrow generator allow-list and generated-source verification.

## Completeness method and evidence limits

The inventory was produced by:

1. reading the exact checked-in M153 `browser_protocol.pdl`, all included
   domain PDLs, and `js_protocol.pdl` rather than inferring status from Rust
   names;
2. searching every production Rust file under `crates/voidcrawl/src` and
   `vendor/chromiumoxide/src` for generated command/event types, generic
   `execute` call sites, controller initialization chains, `CdpEvent` matches,
   and typed event listeners;
3. following VoidCrawl calls through Chromiumoxide helpers (notably
   screenshots, element interaction, cookies, evaluation, page creation, and
   close) so wrapper methods did not hide protocol traffic; and
4. checking each required lifecycle family against focused repository tests.

The exact PDL/input and generated-output drift gate remains
`vendor/chromiumoxide_cdp/scripts/verify-generated.sh`; the M153 shape contracts
remain in `vendor/chromiumoxide_cdp/tests/m153.rs`. A second parser/verifier was
not added because it would duplicate the PDL generator's naming rules. The
public API no longer returns a raw page or CDP target handle.

This document is source-complete for repository-internal production references
at the status date. Its genuine limits are:

- independently managed clients using a browser WebSocket endpoint can issue
  commands outside VoidCrawl's controller path;
- ignored but successfully decoded CDP events are not “used” merely because
  the generated event enum can represent them;
- a source/test reference proves schema and intended behavior, while final
  native/headful/container certification remains a separate CAS-373 runtime
  gate; and
- renderer crash reason/status is not currently captured from a CDP crash
  event, as described above.
