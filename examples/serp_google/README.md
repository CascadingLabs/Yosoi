# Google SERP use case — the spike's runnable dogfood

The "thing to run off of" for the hotpath-dogfood spike. One Google-search program
drives the **real** new engine end-to-end and exercises every workstream:

| WS | What it proves here |
|----|---------------------|
| **W1** | `ReplayPlan` is a behavior tree; a mid-scrape reCAPTCHA is an UNLEARNED `REACTION` that resolves its *description* through the `DiscoveryBus`, hot-swaps a humanized-click recovery, and **resumes** — captcha-recovery and selector-drift-repair are one mechanism |
| **W3** | `teleport`-before-first-paint: the geo override is installed before the first `goto` |
| **W4** | one parametrized program (`params={'q': ...}`) replays across N queries; the new `execute_plan(..., resolver=)` seam connects the public entry to concurrent discovery |
| **W5** | `OrganicResult` vs `AdResult` share `{url, title}` but differ by docstring → **distinct** cache signatures; `to_model()` exports to a plain pydantic/ODM model |

## Run

```bash
uv run python examples/serp_google/google_serp.py              # offline demo (default)
uv run python examples/serp_google/google_serp.py --queries 30 --captcha-on 12
uv run python examples/serp_google/google_serp.py --real       # live-path status (gated)
```

The default run is **offline and deterministic** — a `FakeTab` models Google and
raises a rendered reCAPTCHA on the Kth search, so the whole react-and-resume path
runs with no network and no LLM. It's pinned by `tests/integration/test_serp_google_demo.py`.

## Going live (`--real`)

The live loop drives `_VoidCrawlFetcher.fetch_with_plan(plan, params)` against a pooled
VoidCrawl tab. The captcha **guard** already works on a pooled tab (it uses the
`CAPTURE_JS` widget probe). Two follow-ups gate the full live loop (see
`findings/W1.md` / `findings/W4.md`):

1. VoidCrawl `PageResponse` needs an `antibot` field for the W4 goto-level gate (today inert → no false blocks).
2. `capture/inject/solve_captcha` need binding on `PooledTab` so a real solver token can flow from PLANE B.

Until then the program **detects** and **reacts** live; only the real-solver token is stubbed.
The next step is wiring discovery to *emit* this program for `google.com` so it's discovered, not hand-built.
