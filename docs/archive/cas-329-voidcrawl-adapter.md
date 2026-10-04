# CAS-329 VoidCrawl adapter

`yosoi-web-capture-voidcrawl` is the concrete in-process browser acquisition adapter. It launches the requested headless/headful mode with the certified CDP instrumentation mode, creates a fresh disposable Chromium context, applies validated environment overrides, arms bounded collectors before navigation, and returns only Yosoi-owned `BrowserAdapterFacts` after context disposal and session close. It supports event-driven `DomContentLoaded` and full-load `ControllerCompleted` navigation in a fresh isolated context. DOM/AX-only captures can stop the remaining load after `DOMContentLoaded`; response-source captures retain full-load completion so the main response body is not discarded. DOM, AX, source, and layout share capture-local document identity where their providers report it. Provider network frame/loader IDs remain opaque and are not promoted to document scope.

Color-scheme and reduced-motion overrides are independently optional and are sent together through VoidCrawl's single emulated-media command. Viewport/DPR/user-agent, locale, and timezone use VoidCrawl's public page methods. Failure while applying any override still proceeds through context and session teardown.

Load-event, network-idle, visual, runtime, cookies, and storage paths are not silently weakened; unsupported request/policy combinations remain typed failures until their owning follow-up work lands.

## Paired local dependency

This adapter and the VoidCrawl CAS-329 provider are a required paired change: environment capability snapshots, bounded navigation reports, document epochs, and teardown behavior must move together. This change is paired with the VoidCrawl CAS-329 provider change. The adapter manifest intentionally uses a clearly marked temporary relative path to `../voidcrawl-cas-329-provider-dogfood--VoidCrawl/crates/core`. Replace it with an exact reachable Git revision before publication. Neither candidate provider revision `c1cba0dc` nor parent `5eb6dedd` is currently reachable from the remote, so this is not a Final Boss/publication state.

VoidCrawl core itself points directly at its vendored patched `chromiumoxide` with a compatible version. Cargo does not inherit a dependency repository's workspace-root `[patch.crates-io]`; therefore consumers of core by path/Git do not require their own hidden patch.
