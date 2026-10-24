# Find and open an article with `ys::surface`

This Rust example follows the CNN recording: observe the first-visit
modal, optionally accept it, find an article by its link text, click its exact
indexed DOM node, and observe the destination heading and body-access state.
No model, index HTTP server, CSS/XPath locator, or Python binding is required.

From this workspace, with regular Chromium Stable and a matching ChromeDriver:

```sh
CARGO_BUILD_JOBS=1 cargo run -p yosoi --features browser --example surface_article -- \
  --url https://www.cnn.com/ --query 'text from a current article link' \
  --accept-terms --output .local/index-article
```

`--accept-terms` authorizes the visible CNN **Agree** action. Omit it to stop
at the legal modal. It never signs in, subscribes, or purchases anything.
For a visible browser, run from a graphical session. A virtual display works too:

```sh
xvfb-run --auto-servernum --server-args='-screen 0 1440x1000x24 -nolisten tcp' \
  /path/to/target/debug/examples/surface_article \
  --query 'text from a current article link' --accept-terms
```

Add `--headless` for Chromium's regular headless mode. Some CNN requests in that
mode returned an `Unknown Error` page during this spike. The example records
failure rather than substituting downloaded HTML or bypassing a challenge.
`CHROME` and `CHROMEDRIVER` override executable paths; sandboxing remains enabled.
The example owns and removes its temporary browser profile and driver.

## The Rust loop

`use yosoi as ys` makes `ys::surface` the SDK namespace in this example.

1. Capture the live light DOM into the SDK's standard rendered-DOM document.
   Retain a map from native document node IDs to actual browser objects.
2. Construct `surface::Session`, create a detached cursor, and `attach` a live reader.
3. Read `overview`, `find`, and `inspect` with a **4,096-byte response budget**.
   Follow index parents to an actionable link; paginate bounded search results.
4. Resolve the index's `dom_node` coordinate through the captured object map.
   Compare its indexed href with the live href. Check document membership,
   visibility, the first client rectangle's viewport intersection, hit testing,
   and disabled/inert state.
5. `focus` the reference, `promote` the cursor, and `begin_action`. Recheck the
   live target and SDK lease immediately before `mark_dispatched` and the
   browser's native element click.
6. Observe the new document with mutation/load events and a timeout bound.
   Publish fresh evidence and finish with a receipt. A confirmed navigation may
   still have `subscription_required` body access.

The trace contains complete bounded index responses, eligibility evidence,
cursor transitions, native dispatch, postconditions, receipts, and elapsed times.
`before.png`, `after.png` (or `failure.png`), and `trace.json` go in `--output`.
The summed index-read bytes exclude raw browser capture/transport and screenshots;
this is not a measured model-token claim.

## Outcome and limits

- `readable`: changed URL, visible H1, at least three visible long paragraphs
  totaling 500 characters, no recognized subscription message, and document load
  complete at the observation. This is a heuristic, not semantic verification of
  the entire article or a guarantee that an overlay cannot appear later.
- `subscription_required`: changed URL and visible H1, with a recognized visible
  subscription message. The example stops and reports the gate.
- `timeout`: the requested postcondition was not observed within 15 seconds.
  The click receipt is unconfirmed; a URL change alone is insufficient.
- `consent_required`: no acceptance was authorized, so no article click occurred.

This is an example-only ChromeDriver adapter around the real Rust index SDK.
Yosoi's production browser provider remains Chromiumoxide. The adapter currently
covers light DOM, same-tab links, and the visible CNN consent modal; it does not
implement shadow trees, cross-origin frame traversal, automatic scroll/retry,
new-tab adoption, continuous capture subscriptions, or automatic article
fallback. Native click errors are preserved as unconfirmed outcomes after
dispatch. A DOM/hit-test race is still possible and is handled conservatively.
Only the selected target is revalidated; unrelated advertisements may mutate.

## Capture normalization

Real CNN advertising iframe `srcdoc` attributes contained DEL control characters
that the existing v1 DOM wire rejects. The example adapter reversibly encodes
only affected attribute/text strings as **JSON string content**. Each capture
records the native node ID, field, encoding, and control count in
`normalized_strings`; decode a marked value with `JSON.parse('"' + value + '"')`.
This is an explicit adapter projection, not a byte-exact raw DOM claim. Nodes
and native object bindings remain intact. An affected href cannot pass the raw
live-href equality check by accident. Other schema-validation failures stop the
run and save the rejected capture for diagnosis.

## Focused native verification

Build the example once, then supply its executable to the optional Node verifier:

```sh
node crates/yosoi/examples/surface_article/verify.mjs \
  target/debug/examples/surface_article .local/index-article-verification
```

The verifier runs one regular headless Chromium at a time against its own local
fixture. Six cases cover a free article, a nested subscription message, an
occluding overlay, withheld consent, control characters in `srcdoc`, and a
click that produces no navigation. The article link also wraps across lines and
has enough attributes to require inspection continuations. Assertions cover
native dispatch/receipts, gate reporting, reversible capture projection, and the
4,096-byte response ceiling. No live website is involved in these regressions.

For agent-selected steps in a persistent browser, use
[`yosoi surface drive`](../../src/bin/yosoi/surface_command/README.md).
It exposes bounded JSON commands for reading, cursor authority, native actions,
refresh, and receipts instead of running this fixed article workflow.
