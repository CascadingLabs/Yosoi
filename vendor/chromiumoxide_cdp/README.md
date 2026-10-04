# Vendored Chromiumoxide CDP bindings

This is Yosoi's checked-in generated protocol crate for the exact Chrome
candidate recorded in [VENDORING.md](VENDORING.md). It is not the upstream
Chromiumoxide controller crate and it does not regenerate during a normal
Cargo build. `src/cdp.rs` is an auditable build input.

The remaining API notes below originate with Chromiumoxide 0.9.1 and describe
the generated command and event conventions retained by this fork.

![Build](https://github.com/mattsse/chromiumoxide/workflows/Continuous%20integration/badge.svg)
[![Crates.io](https://img.shields.io/crates/v/chromiumoxide.svg)](https://crates.io/crates/chromiumoxide)
[![Documentation](https://docs.rs/chromiumoxide/badge.svg)](https://docs.rs/chromiumoxide)

chromiumoxide provides a high-level and async API to control Chrome or Chromium over the [DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/). It comes with support for all types of the [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/) and can launch a [headless](https://developers.google.com/web/updates/2017/04/headless-chrome) or full (non-headless) Chrome or Chromium instance or connect to an already running instance.

## Usage

```rust
use futures::StreamExt;

use chromiumoxide::browser::{Browser, BrowserConfig};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // create a `Browser` that spawns a `chromium` process running with UI (`with_head()`, headless is default)
    // and the handler that drives the websocket etc.
    let (mut browser, mut handler) =
        Browser::launch(BrowserConfig::builder().with_head().build()?).await?;

    // spawn a new task that continuously polls the handler
    let handle = tokio::spawn(async move {
        while let Some(h) = handler.next().await {
            if h.is_err() {
                break;
            }
        }
    });

    // create a new browser page and navigate to the url
    let page = browser.new_page("https://en.wikipedia.org").await?;

    // find and click the search toggle button to reveal the search bar
    page.find_element(".search-toggle").await?.click().await?;

    // find the search bar type into the search field and hit `Enter`,
    // this triggers a new navigation to the search result page
    page.find_element("input[name='search']")
        .await?
        .click()
        .await?
        .type_str("Rust programming language")
        .await?
        .press_key("Enter")
        .await?;

    let html = page.wait_for_navigation().await?.content().await?;

    browser.close().await?;
    handle.await?;
    Ok(())
}
```

The current API still lacks some functionality, but the [`Page::execute`](src/page.rs) function allows sending all `chromiumoxide_types::Command` types (see [Generated Code](README.md#generated-code)). Most `Element` and `Page` functions are basically just simplified command constructions and combinations, like `Page::pdf`:

```rust
pub async fn pdf(&self, params: PrintToPdfParams) -> Result<Vec<u8>> {
    let res = self.execute(params).await?;
    Ok(base64::decode(&res.data)?)
}
```

If you need something else, the `Page::execute` function allows for writing your own command wrappers. PRs are very welcome if you think a meaningful command is missing a designated function.

### Add chromiumoxide to your project

`chromiumoxide` only supports the [`tokio`](https://github.com/tokio-rs/tokio) runtime.

## Generated Code

The `chromiumoxide_pdl` crate parses Chromium's PDL definitions and generates
Rust types. Generation for this fork is explicit and never runs from
`build.rs`:

```bash
CARGO_BUILD_JOBS=1 cargo run -p chromiumoxide_cdp --example generate --offline --locked
vendor/chromiumoxide_cdp/scripts/verify-generated.sh
```

Refresh the exact tagged PDL inputs and checksum manifests first. See
[VENDORING.md](VENDORING.md) for source identities and the complete procedure.

Every chrome pdl domain is put in its own rust module, the types for the page domain of the browser_protocol are in `chromiumoxide_cdp::cdp::browser_protocol::page`, the runtime domain of the js_protocol in `chromiumoxide_cdp::cdp::js_protocol::runtime` and so on.

[vanilla.aslushnikov.com](https://vanilla.aslushnikov.com/) is a great resource to browse all the types defined in the pdl files. This site displays `Command` types as defined in the pdl files as `Method`. `chromiumoxid` sticks to the `Command` nomenclature. So for everything that is defined as a command type in the pdl (=marked as `Method` on [vanilla.aslushnikov.com](https://vanilla.aslushnikov.com/)) `chromiumoxide` contains a type for command and a designated type for the return type. For every command there is a `<name of command>Params` type with builder support (`<name of command>Params::builder()`) and its corresponding return type: `<name of command>Returns`. All commands share an implementation of the `chromiumoxide_types::Command` trait.
All Events are bundled in single enum (`CdpEvent`)

## Fetcher

By default `chromiumoxide` will try to find an installed version of chromium on the computer it runs on.
It is possible to download and install one automatically for some platforms using the `fetcher` feature.

You need to enable either the `rustls` or the `native-tls` feature and the `zip0` or `zip8` feature to allow the fetcher to download binaries.

```rust
use std::path::Path;

use futures::StreamExt;
use chromiumoxide::browser::{BrowserConfig};
use chromiumoxide::fetcher::{BrowserFetcher, BrowserFetcherOptions};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let download_path = Path::new("./download");
    tokio::fs::create_dir_all(&download_path).await?;
    let fetcher = BrowserFetcher::new(
        BrowserFetcherOptions::builder()
            .with_path(&download_path)
            .build()?,
    );
    let info = fetcher.fetch().await?;

    let config = BrowserConfig::builder()
        .chrome_executable(info.executable_path)
        .build()?,
}
```

## Known Issues

- The rust files generated for the PDL files in [chromiumoxide_cdp](./chromiumoxide_cdp) don't compile when support for experimental types is manually turned off (`export CDP_NO_EXPERIMENTAL=true`). This is because the use of some experimental pdl types in the `*.pdl` files themselves are not marked as experimental.

## Troubleshooting

Q: A new chromium instance is being launched but then times out.

A: Check that your chromium language settings are set to English. `chromiumoxide` tries to parse the debugging port from the chromium process output and that is limited to english.

## License

Chromiumoxide source remains available under MIT or Apache-2.0. The Chromium
browser PDL inputs are redistributed under [LICENSE-CHROMIUM](LICENSE-CHROMIUM),
and the V8 JavaScript PDL input is redistributed under
[LICENSE-V8](LICENSE-V8). Generated protocol output retains the notices and
provenance recorded in this directory.

Licensed under either of these:

- Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or
  <https://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or
  <https://opensource.org/licenses/MIT>)

## References

- [chromedp](https://github.com/chromedp/chromedp)
- [rust-headless-chrome](https://github.com/atroche/rust-headless-chrome) which the launch config, `KeyDefinition` and typing support among others is taken from.
- [puppeteer](https://github.com/puppeteer/puppeteer)
