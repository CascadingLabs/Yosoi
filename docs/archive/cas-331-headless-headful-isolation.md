# CAS-331 headless/headful and fresh-context conformance

## Shared execution semantics

Headless and headful are modes of the same `ResolvedBrowserCaptureSpec` and the same VoidCrawl adapter path. Each attempt launches an owned Chromium session, creates a fresh disposable isolated context, applies the resolved rendering overrides, arms collection before navigation, resolves the same terminal precedence, disposes the context, and closes the session before returning owned Yosoi facts. The adapter never changes a requested headful attempt into headless.

The effective provider visibility is mapped exhaustively to `BrowserMode` and must match both the resolved attempt environment and the certified navigation capability profile. Semantic parity tests compare readiness, terminal kind, cleanup, and the ordered artifact-family outcome shape. Timing and screenshot bytes are factual per-attempt outputs and are not compared across modes.

## Display boundary

A headful attempt requires an explicitly configured graphical display. The adapter recognizes a nonempty X11 `DISPLAY` or Wayland `WAYLAND_DISPLAY` as configured and otherwise returns `HeadfulDisplayUnavailable` before browser launch or fixture access. A configured but unusable display remains a typed provider launch failure; it is never retried as headless.

Headful CI must provide its display externally, for example through the CI compositor or Xvfb wrapper. Tests do not mutate process-global display variables. Hosts without a configured display exercise the explicit unavailable path rather than claiming headful execution.

## Fresh-state boundary

The foundational adapter owns a newly launched browser process and fresh isolated context for every attempt. Sequential and concurrent deterministic fixtures verify that cookies, local storage, and session storage written by one attempt are absent from every other attempt. The adapter has no cookie import/export, persistent-profile, ambient-context attachment, profile lease, arbitrary header, permission mutation, or init-script surface, and CAS-331 makes no such guarantee beyond the fresh launched-process/context boundary.

Cache and service-worker behavior remain visible as network provenance where the provider reports them, but detailed process-tree and repeated cache/service-worker soak coverage belongs to CAS-333 certification. Persistent or managed browser state is a later browser-enhancement project.

## Deterministic checks

- `conversions::tests::browser_mode_conversions_preserve_headless_and_headful`
- `capture::tests::headful_display_detection_accepts_supported_displays_only`
- `sequential_fresh_contexts_do_not_leak_browser_state`
- `concurrent_fresh_contexts_do_not_share_browser_state`
- `headful_uses_shared_adapter_semantics_or_reports_missing_display`

Visual conformance is structural: PNG validity, dimensions, viewport/DPR facts, document epoch, and layout relationship. Pixel equality across headless/headful, GPU, font, compositor, or display environments is not asserted.
