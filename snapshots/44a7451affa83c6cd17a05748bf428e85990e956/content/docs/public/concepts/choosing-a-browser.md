---
title: 'Choosing a browser'
description: 'Select Chrome, Firefox or a headless Moli profile for a browser acquisition.'
order: 4
---

# Choosing a browser

Chrome/CDP remains the default browser. Firefox and Moli use the optional native BiDi controller. Selecting an engine does not install it, change a Direct HTTP request, or retry an operation through another browser.

The optional controller is included in the 0.4.0 release. Published 0.3.0 packages do not contain it. Follow the [installation instructions](../releases/0-4-0.md), or build from a checkout as shown below. Rust needs `browser-bidi`; the 0.4.0 Python wheels include it. The examples also need an installed regular Firefox release. The qualified release is Firefox 158.0.1. `YOSOI_FIREFOX_EXECUTABLE` can select its absolute executable path.

## Install: from a checkout

Set `YOSOI_REPO_ROOT` to the checkout containing the optional controller.

### Cargo

Run this in your Rust application. Tokio needs its `macros` and `rt` features for the example.

```sh
cargo add yosoi --path "$YOSOI_REPO_ROOT/crates/yosoi" --features browser-bidi
```

### uv

Run these commands in the Yosoi checkout, then run the Python example in that environment.

```sh
uv sync --no-install-project
uv run --no-sync maturin develop --features browser-bidi
```

## Example: request Firefox's DOM

Use the same [JavaScript shop](https://qscrape.dev/eshop/javascript/) as [Using a browser](using-a-browser.md). The engine and window mode are separate choices. Here the acquisition requests a headless browser and explicitly selects rendered DOM.

### Rust

```rust
use std::error::Error;
use yosoi::browser::{BrowserConfig, BrowserEngine};
use yosoi::policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy};
use yosoi::request::{self, DocumentOutcome};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = Policy {
        browser: BrowserConfig {
            engine: BrowserEngine::Firefox,
            ..BrowserConfig::default()
        },
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless)
                .documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let response = request::new("https://qscrape.dev/eshop/javascript/")
        .bind(&policy)
        .send()
        .await?;
    let produced = response
        .attempts()
        .flat_map(|attempt| attempt.documents())
        .filter(|selected| matches!(selected.outcome(), DocumentOutcome::Produced(_)))
        .count();
    println!("Retained DOM documents: {produced}");
    Ok(())
}
```

`browser.engine` changes the implementation used for this acquisition. The program counts produced Documents rather than treating a completed Request as proof that every requested representation was available.

### Python

```python
import asyncio
from yosoi import request
from yosoi.browser import BrowserConfig
from yosoi.policy import Acquisition, Page, Policy


async def main():
    policy = Policy(
        browser=BrowserConfig(engine="firefox"),
        page=Page(
            acquisitions=[Acquisition.browser().with_documents(["rendered_dom"])]
        ),
    )
    response = (
        await request.new("https://qscrape.dev/eshop/javascript/")
        .bind(policy)
        .send()
    )
    produced = sum(
        selected.outcome.status == "produced"
        for attempt in response.attempts
        for selected in attempt.documents
    )
    print(f"Retained DOM documents: {produced}")


asyncio.run(main())
```

`BrowserConfig` is shared with retained `Session` acquisition. The Python package passes the declaration to the same Rust controller and preserves the typed acquisition outcomes.

## Inspect what was captured

A produced DOM means the browser returned a retained snapshot. It does not prove that the shop's asynchronous catalog had arrived at capture time. Continue with [Waiting for the page](waiting-for-the-page.md) when your task needs those products.

Arbitrary scripts still require the owning Session's JavaScript permission. Engine capability does not grant that permission. Timeout or cancellation after possible dispatch can leave an Unknown result; changing engines must not be used to silently repeat that action.

## Choose a Moli profile

Custom `Policy.network` routing uses Yosoi's owned TCP relay for Chrome and owned Firefox or Moli sessions. Native BiDi engines apply the local SOCKS route separately to each created user context. Remote Firefox and Moli endpoints reject a nondefault route before connecting. Direct HTTP Requests continue to use the selected network policy.

Moli 1.1.19 is headless-only. Its DOM profile supports reading and scripts without claiming accurate visual geometry. Choose layout deliberately for pointer input or PNG capture.

| Choice           | Window              | Native input                      | Session PNG          |
| ---------------- | ------------------- | --------------------------------- | -------------------- |
| Chrome/CDP       | Headless or headful | Existing Chrome path              | Existing Chrome path |
| Firefox/BiDi     | Headless or headful | Main-document targets             | Viewport             |
| Moli DOM/BiDi    | Headless            | Unsupported                       | Unsupported          |
| Moli layout/BiDi | Headless            | Revalidated main-document targets | Viewport             |

The Moli input adapter refreshes layout through discarded raster observations, so its Click and EnterText operations also require Screenshot permission. Embedded browsing-surface input is unsupported. Frame scripts use a separately validated current realm. BiDi text entry accepts printable Unicode and rejects control characters and the reserved WebDriver key block.

Firefox also supports a browser `response_document`: the retained HTTP response after content decoding, separate from the DOM changed by scripts. Moli can capture selected Fetch/XHR response bodies, but its isolated contexts omit the top-level navigation response body. Requesting that response document from Moli produces a policy-resolution failure before navigation. The caller's retained Work remains usable.

Firefox's native text conversion can alter non-UTF-8 response bytes. Captures require a matching decoded byte extent, or the encoded body size when the response is uncompressed. Altered or unverifiable bodies remain unavailable, including compressed responses when Firefox omits their decoded size.

Both engines support DOM and selected-response Until watches, including bounded JSON-body confirmation. BiDi confirmation records identify their protocol, frame and document epoch. They do not invent a CDP loader ID. Request-start timestamps retain BiDi's millisecond precision; a request whose start cannot be established after its trigger cannot confirm that trigger.

| Capture or confirmation                   | Firefox/BiDi | Moli/BiDi      |
| ----------------------------------------- | ------------ | -------------- |
| Rendered DOM document                     | Supported    | Supported      |
| HTTP response document                    | Supported    | Unsupported    |
| DOM Until confirmation                    | Supported    | Supported      |
| Selected response/JSON Until confirmation | Supported    | Supported      |
| Full browser AX document or AX Until      | Unsupported  | Unsupported    |
| Viewport Session PNG                      | Supported    | Layout profile |

BiDi does not expose a full browser accessibility-tree export. An accessibility locator match is not equivalent to membership in the exposed AX tree. Choose Chrome/CDP when the workflow requires that representation. Yosoi does not replace AX evidence with a DOM-derived approximation or silently switch protocols.

The controller also retains bounded network and runtime facts when the capture requests them. Moli's network graph is marked incomplete because its top-level document events are missing, and it cannot prove network quiet. Console messages are available on both engines; Moli's uncaught-exception coverage remains incomplete. A missing cache or service-worker fact stays unknown. The public `network_tree` Document view remains unavailable independently of these collectors.

Cookie and localStorage state can persist within the supported Session boundary; cookie/storage artifact export remains unsupported. A screenshot does not establish WebGL support or Chrome pixel parity.

## Example: use a Moli service

The repository's [Moli container](https://github.com/CascadingLabs/Yosoi/tree/main/docker/moli) provides a pinned non-root, read-only runtime with bounded resources. Start its layout profile from the checkout:

```sh
MOLI_PROFILE=layout docker compose -f docker/moli/compose.yaml up --build -d
```

Replace the first example's browser declaration with the matching service profile.

### Rust

```rust
use yosoi::browser::MoliProfile;

policy.browser = BrowserConfig {
    engine: BrowserEngine::Moli,
    endpoint: Some("ws://127.0.0.1:9222/session".to_owned()),
    moli_profile: MoliProfile::Layout,
    ..BrowserConfig::default()
};
```

Make the earlier `policy` binding mutable for this variation. A configured executable and an existing endpoint are mutually exclusive. Omit the endpoint to launch an installed Moli executable instead.

### Python

```python
policy.browser = BrowserConfig(
    engine="moli",
    endpoint="ws://127.0.0.1:9222/session",
    moli_profile="layout",
)
```

The declaration does not change the running server. Match its layout/resource settings. The client owns its logical session and created contexts, while the operator owns the service process.

## Keep identity and policy visible

Native observations and receipts retain separate controller, protocol, engine and profile identity. An owned executable can supply a release version and SHA-256. A remote Moli server currently omits its engine version; records preserve that absence instead of substituting its Chrome-style user agent.

Owned Moli launches and the supplied container block private-network requests by default. Local fixtures require an explicit exception on the server and in the matching declaration. The native filter is not a universal network firewall; an external endpoint does not attest its egress policy. The container guide documents the run, profile and export settings.
