# Drive a live surface from a coding agent

The Rust API is `ys::surface` (`use yosoi as ys`), with
`Surface`, `SurfaceError`, references, budgets, cursors, and sessions. The old
unreleased `ys::index` namespace and `index-images` feature are removed. Use
`surface-images` for image support without the browser feature.

Build and start the CLI from this workspace:

```sh
CARGO_BUILD_JOBS=1 cargo build -p yosoi --features cli --bin yosoi
./target/debug/yosoi surface drive --url https://www.cnn.com/ --headless
```

The process owns one isolated browser and stays alive while the coding agent
reads replies and writes its next command. It is a JSON-lines protocol: one
request and one response per line on stdin/stdout, with an optional `id` echoed
in the reply. Keep the process's stdin open between tool calls. Use a PTY and
`write_stdin` for an interactive agent session, or ordinary pipes for a driver.
PTY terminal echo is separate from the program's JSON stdout.

For a visible browser, omit `--headless`. In an environment without a display:

```sh
xvfb-run --auto-servernum --server-args='-screen 0 1440x1000x24 -nolisten tcp' \
  ./target/debug/yosoi surface drive --url https://www.cnn.com/
```

The current web adapter uses regular Chromium and ChromeDriver; it
shares the article example's transport. It does not replace Yosoi's production
Chromiumoxide provider. Set `CHROME` and `CHROMEDRIVER` to select executables.
Sandboxing and site isolation stay enabled. CNN sometimes returns `Unknown
Error` to headless requests; the headed variant is available for that case.

## A coding agent's loop

The ready reply includes the current capture, root reference, browser version,
and a **detached** cursor. Start reading, locate an actionable node, then acquire
hot authority explicitly:

```json
{"id":"1","op":"attach"}
{"id":"2","op":"overview"}
{"id":"3","op":"find","query":"Agree"}
```

Copy an exact `{ "capture": "...", "node": 123 }` reference from a reply into
subsequent requests. Inspect it; if it addresses text, follow `parent` to the
link or button. The opaque node ordinal is not the browser's native node ID.

```json
{"op":"inspect","reference":{"capture":"COPY_CAPTURE","node":123}}
{"op":"parent","reference":{"capture":"COPY_CAPTURE","node":123}}
{"op":"eligibility","reference":{"capture":"COPY_CAPTURE","node":122}}
{"op":"hot"}
{"op":"click","reference":{"capture":"COPY_CAPTURE","node":122},"expect":{"kind":"text","text":"Legal Terms and Privacy","present":false}}
```

That last example is the consent action; the agent should issue it only when
its user has authorized acceptance. The CLI does not accept terms automatically.
The click reply includes its receipt and the newly published capture. Locate
the article again using **new references**:

```json
{"op":"find","query":"North Korea"}
{"op":"inspect","reference":{"capture":"NEW_CAPTURE","node":456}}
{"op":"click","reference":{"capture":"NEW_CAPTURE","node":456},"expect":{"kind":"article"}}
{"op":"overview"}
{"op":"article"}
{"op":"close"}
```

Article labels change over time; this query matched a free CNN article during
local verification on 2026-10-24. Selection comes from surface reads, not a
preconfigured CSS/XPath selector. An article postcondition verifies the indexed
link's destination path and a visible H1, then records readable body text or a
recognized subscription gate. Body access uses the article example's documented
heuristic; it is not semantic verification of an entire article.

## Operations

| `op` | Fields and behavior |
| --- | --- |
| `status`, `attach`, `detach` | Inspect or change observation attachment. Detach revokes hot authority. |
| `overview`, `find` | Bounded reads; `find` takes `query`. |
| `inspect`, `expand`, `parent` | Take an exact `reference`; inspections may need continuation chunks before JSON parsing. |
| `focus`, `hot`, `cool` | Move focus or acquire/release the single hot capability. |
| `eligibility` | Inspect live document membership, captured target equality, layout, click point, occlusion, and disabled state. |
| `wait` | Takes `text` and `present`; waits through document events, then publishes a fresh capture. Requires attachment. |
| `refresh` | Capture the browser again and invalidate prior action references. |
| `click` | Takes `reference`; optional `expect` is `{"kind":"navigation"}`, `{"kind":"article"}`, or `{"kind":"text","text":"...","present":true}`. Without a postcondition, dispatch remains unconfirmed. |
| `fill` | Takes `reference` and `text`; clears/types natively, then verifies the live value without echoing it. |
| `key` | Takes `reference` and `key`: `Enter`, `Tab`, `Escape`, or `Backspace`. Dispatch remains unconfirmed; inspect the result. |
| `scroll` | Takes the current **root** `reference`, `delta_y`, optional `delta_x`; each delta is limited to 10,000 pixels. |
| `navigate` | Takes current root `reference` and HTTP(S) `url`; requires hot authority and observes the resulting location. |
| `article`, `screenshot` | Read live article-access metadata or write `surface.png` in the evidence directory. |
| `close` | Release the browser and exit. EOF, Ctrl-C, and SIGTERM also clean up. |

Each request can specify `budget` (default 4096, range 1024–16384), `items`
(default 20, maximum 100), and a `continuation` copied unchanged from a previous
response. The byte budget bounds the **entire JSON reply**, excluding its newline.
Input lines are limited to 64 KiB, IDs to 64 serialized bytes, and effects require
at least a 4096-byte reply budget. Invalid commands return an error and keep the
session available; stale or blocked targets never silently retarget.

This driver publishes explicit snapshots; it does not claim continuous mutation
subscription coverage. Before an effect it compares the actual captured node's
attributes, text, live value, URL, document, and click eligibility. Unrelated page
changes do not require a whole-page idle period. References from previous
captures are rejected. A mutation between final validation and dispatch can
still occur; native failures and missing postconditions remain unconfirmed.
Shadow DOM, iframe traversal, new-tab adoption, and automatic retries are outside
this initial adapter. All effects use native WebDriver commands, without an
arbitrary-JavaScript execution command exposed to the agent.

`--output` defaults to `.local/surface-session`. The bounded trace keeps its latest
1024 events and reports `dropped_events`. Capture string projections are explicit
in its capture events, as documented in the article example.

## Native verification

```sh
node crates/yosoi/src/bin/yosoi/surface_command/verify.mjs \
  target/debug/yosoi .local/surface-cli-verification
```

The verifier drives actual JSON requests and native effects against its own
local site, checking reader/hot authority, consent, stale references, fill/key,
covered targets, article navigation, inspection continuations, small reply
budgets, screenshots, scroll/navigation, subscription gates, command-error
recovery, and close. It runs one browser at a time and saves its transcript.

## Archive recording policy and repetition

Enable the per-session recording policy explicitly with `--archive DIR`:

```sh
yosoi surface drive --headless \
  --url https://cascadinglabs.com/yosoi/getting-started/what-is-yosoi/ \
  --archive .local/docs-version-archive --output .local/docs-version-run
```

Without that option, recording policy is off and the session writes only its
bounded diagnostic trace. With it, every capture is a normal archived rendered-DOM
`Document`; HTML is retained in normal `AutomationRecord` observations. Capture
receipts link the full Document reference, surface identity, and explicit string
projection metadata. Command receipts preserve observed/rejected/unknown status.
The existing Archive format and AutomationRecord schema are unchanged.

Each successful command checkpoints a new immutable AutomationRecord. The small
`record.json` file in `--output` is an atomic latest-handle pointer, containing the
archive location and normal `AutomationRecordRef`. Completed browser cleanup seals
the run; live repetition rejects unsealed records. Archive errors detach authority
and block further effects rather than silently continuing unrecorded.

For live repetition, provide an explicit semantic intention on each click. It is
validated against the selected surface reference before dispatch:

```json
{"op":"click","reference":{"capture":"COPY_CURRENT_CAPTURE","node":65},"target":{"query":"Documentation release","tag":"summary"},"expect":{"kind":"text","text":"v0.1.0","present":true}}
{"op":"find","query":"v0.1.0"}
{"op":"click","reference":{"capture":"COPY_NEW_CAPTURE","node":94},"target":{"query":"v0.1.0","tag":"a"},"expect":{"kind":"text","text":"This page is unavailable in v0.1.0. Showing the overview.","present":true}}
{"op":"close"}
```

Those node numbers illustrate one capture only. The agent must use the current
references returned by its own `find`/`inspect`/`parent` calls. No CSS/XPath locator
is stored. The archived target query and tag express what to find again; the
captured reference records what was actually acted on.

Reopen saved evidence without network or browser execution:

```sh
yosoi surface replay --record .local/docs-version-run/record.json \
  --repeat 3 --query 'This page is unavailable'
```

This reads and validates the normal AutomationRecord and each linked Document,
rebuilds surfaces with identical capture identities, and constructs normal offline
Views from retained HTML. It grants no live cursor authority. `--query` returns a
bounded search of the final surface. Browser executables are not required.

To repeat the clicks against the live site:

```sh
yosoi surface repeat --record .local/docs-version-run/record.json \
  --count 3 --headless --output .local/docs-version-repeat
```

Each iteration starts a fresh browser profile and session, attaches a reader,
acquires hot authority, resolves every intention through surface reads, checks
uniqueness and live eligibility, and requires its recorded postcondition. Each
iteration writes its own normal archived record and final screenshot. Browser
session identity is included in captured Document identity, so archived references
cannot substitute for fresh live references. Ambiguous, stale, rejected, or
unconfirmed targets stop repetition; there is no selector fallback.

Counts are bounded to 1–100 and iterations run serially. This first live repeater
supports recorded **clicks with explicit targets and postconditions**. It rejects
records containing other effects or incomplete click intentions. Offline replay
can inspect all recorded receipts. Screenshots remain local proof files; this
policy archives the text DOM and HTML, not image bytes or application memory.
The existing AutomationRecord retention limits apply; oversized recordings fail
explicitly. Browser captures are still explicit snapshots, not continuous history.

The video's expected endpoint is the site's `v0.1.0` overview: that release does
not contain the current “What is Yosoi?” page, and the site displays its fallback
notice. No documentation or site settings are changed by the test.

Run focused Archive integration verification against a local version-menu fixture:

```sh
node crates/yosoi/src/bin/yosoi/surface_command/verify_recording.mjs \
  target/debug/yosoi .local/surface-recording-verification
```

It verifies the normal Archive/AutomationRecord path, offline reconstruction with
browser executables disabled, no network requests during offline replay, rejection
of unsealed live recipes, three live iterations, and fresh capture identities.

The second provider is now `surface video --file FILE`. `surface web` is the
canonical live-web command (`drive` remains an alias). Both support the shared
`describe` / `read` / `focus_evidence` protocol. See the
[two-surface experiment](../../../surface/README.md) for DTOs, read-only video,
frame/crop capabilities, resource bounds, and decoder-free Archive replay.
