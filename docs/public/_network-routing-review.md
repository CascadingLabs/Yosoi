# Network routing review receipt

Page job: show how to choose a network route once and retain it through Requests
and owned browser Sessions, with the same declarations in Rust and Python.

Source workspace: `/home/andrew/Desktop/cl/yosoi-network-policy`.
Comparison base: `42168a93` on `main`. The implementation, tests, and prose are one
draft PR; publication and release are outside this change.

## Claims and examples

- `Policy.network` validates and snapshots family, source, and proxy URL. Its
  non-default value participates in effective identity and archive validation.
  Default omission preserves existing JSON and identity behavior.
- `choose IPv6`, `use an upstream proxy`, and `retain the route in a Session`
  use the current public `policy`, `request`, and `session` interfaces. Both
  languages share the native transport and lifetime implementation. QScrape
  URLs are runnable examples, not claimed live IPv6 availability evidence.
- Controlled loopback fixtures observe source IPs and delivered content.
  Browser coverage includes frames, fetches, workers, service workers, and
  WebSockets. Negative fixtures verify family enforcement and proxy failure
  without direct fallback. Cancellation verifies upstream socket closure.
- Upstream family means the connection to the proxy. Destination egress,
  operating-system DNS, and process-wide firewall guarantees remain distinct.
- Proxy credentials are redacted from diagnostic representations and retained
  in serialized policy snapshots. The page states that storage boundary.

## Review choices

The concept follows the existing small paired-program format. It introduces
strict family selection, adds an external proxy, then retains that choice in a
Session. The new page joins the Concepts navigation and the SDK policy table
links to it. No existing public route or release page is renamed.

The Chromium proxy configuration preserves sandboxing and site isolation.
Actual browser arguments exposed an existing double-prefix bug in proxy-server
construction. The proxy value now uses the controller's typed switch builder.
An authenticated proxy with an unresolvable origin proves that browser traffic
uses the helper. Resolver enforcement belongs in outbound sockets, rather than
a catch-all browser host-resolver rule.

## Validation record

The compiler API artifact selects
`e29aabfbf347c3fe0f2b39886cf3d2d2ed19c562`, with the `browser` feature. The
delivery revision adds evidence records, a concrete-source guard, and the sparse
default observations without changing the public API inventory. The scoped
contract grows from 2,427 to 2,450 declarations; existing signatures and semantic
mappings are preserved. No scoped SDK declaration is unmapped.

Focused local verification:

- SDK all-features library check; SDK, development-support, and benchmark
  all-targets Clippy; additional library Clippy after source hardening.
- Eleven tunnel/policy/archive tests and eight public routing tests, including
  the authenticated browser proxy proof. Thirty-six existing policy tests and
  eleven archive compatibility tests pass. The two subprocess-only archive
  harness entries run through their parent test.
- Twenty-two native-backed Python policy/network/error/browser checks. The ten
  network checks pass again after constructor-error redaction changes.
- Fifteen Serde-runner tests preserve rejection of inferred defaults and
  mismatched typed values. All 67 Rust-authored wire fixtures and 109 standard
  evidence cases pass.
- Ruff, focused Python type checks, documentation reference tests, and the docs
  gate pass. The docs gate validates 605 pages and runs 25 tests. Three Rust
  learning programs typecheck against the compiled browser SDK; three Python
  programs parse. The QScrape IPv4 HTTPS smoke returns HTTP 200 with 4,053 HTML
  bytes. Live public IPv6 reachability is not claimed.

The regular eligible browser is Google Chrome `156.0.8078.47`, executable
SHA-256 `95dc9473b4f904cb3ab0800fc7206081fcae12abc094a088bd741a13f1747b72`.
The VoidCrawl integration, Chromiumoxide controller base, and generated CDP schema
retain their separately documented identities in the
[browser baseline](../chromium-cdp-baseline.md). These are routing regressions,
not a new controller/schema/browser certification.

The existing CascadingLabsFE preview runs from its own workspace with
`YOSOI_REPO_ROOT` selecting this Yosoi workspace and an explicit fresh API
artifact. Actual served HTML verifies the new concept, both language variants,
and the Rust/Python Network reference fields and prose. Browser UI surfaces were
unavailable, so no manual visual or interactive browser review is claimed.

Detailed machine-local proofs are retained in `.generated/network-policy/`.
Hosted checks on the pushed PR head and current base remain the delivery gate;
their authoritative result is the PR check rollup.
