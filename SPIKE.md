# Spike: hotpath-dogfood — force Yosoi back onto Nimbal's scraping hotpath

**Branch:** `spike/hotpath-dogfood` · **Base:** `main` (f7debc1) · **Opened:** 2026-06-05
**Source notes:** [`notes.md`](./notes.md) (captured while running Nimbal in production)
**Dogfood target:** `/home/andrew/Desktop/Work/nimbal` (`nimbal/core/web/`)

---

## Thesis

Yosoi got **kicked to the curb** in Nimbal's production hotpath. The coding agents
building Nimbal reached for raw VoidCrawl + hand-written selectors instead of Yosoi's
discover-once / replay-forever engine. That is a rational local choice for 2–3 sites —
and a losing one at 30+ sites whose selectors drift over time, which is exactly the
problem Yosoi exists to solve.

**Executive decision:** force Yosoi onto Nimbal. Use the real pain points from the
production run as the backlog for making the *Yosoi engine* better, and let Nimbal be
the dogfood harness that proves each fix on live anti-bot SERP/authority targets.

This spike is the long-running process that drives that: for each pain point below,
produce either a **direct fix in Yosoi** or a **documented answer** (a designed
mechanism, a measured finding, or a reasoned "won't fix / out of scope").

## Evidence — Yosoi is bypassed in the hotpath today

In `nimbal/core/web/_real.py`:

- **`real_serp`** — raw `voidcrawl.BrowserSession` + a hardcoded `_SERP_JS` string that
  selects `#rso a h3, #search a h3`. That is precisely the Google-specific, layout-fragile
  selector Yosoi is meant to discover and keep resilient. Only Google is covered; Bing /
  Brave are TODO (`nimbal/todo.md`).
- **`real_authority`** — raw VoidCrawl + per-tool JS from `scripts/scrape_authority.py`.
  Captcha is detected (`page.detect_captcha()`) only to be recorded as
  `status="blocked:recaptcha"` and abandoned — no recovery, no replay-through.
- **`yosoi_bridge.py`** — *does* define Yosoi `Contract`s (`MapsListingExtract`,
  `SeoRowExtract`), but they are gated behind a `try/except` and **not wired into the
  SERP/authority path at all**. Yosoi is present as a dependency and absent as an engine.

Net: the part of Nimbal that actually fights anti-bot at scale runs zero Yosoi.

## Why agents preferred raw VoidCrawl (hypotheses to confirm)

These are the suspected reasons Yosoi lost the hotpath. The spike validates/refutes each:

1. **Non-linear anti-bot.** Yosoi's `ReplayPlan` is a flat, linear `for node in plan.nodes`
   loop (`yosoi/core/replay/runtime.py:69`) with no concept of a captcha interrupting
   mid-flow. Real SERP/authority scraping hits captcha *non-deterministically*. Raw
   VoidCrawl lets the agent handle it inline; Yosoi can't replay through it. → **Note #3, highest priority.**
2. **Identity/escalation isn't in the engine.** The hotpath hardcodes one trusted Chromium
   profile (`_real.py` `LIVE_PROFILE`); Google needs headful + trusted-profile escalation
   while Bing/Brave/DDG work plain-headless (`nimbal/todo.md`). Yosoi has no profile-cascade
   or per-IP-vs-per-profile blocking model. → **Note #4.**
3. **Teleport is slow / double-loads** and only `set_geolocation` one-shot in the runtime
   (`runtime.py:360`). SERP localization is core to the product. → **Notes #6, #7.**
4. **Contract ergonomics.** No clean path from a Yosoi contract to the consumer's ODM
   (Beanie/Mongo) without a hand-written adapter, and redundant near-identical contracts
   per page are awkward to express. → **Notes #1, #2 (low priority).**

## Workstreams (priority-ordered, each = fix-or-answer)

| # | Note | Yosoi gap | Deliverable |
|---|------|-----------|-------------|
| **W1** | #3 **VERY high** | `ReplayPlan` linear, no captcha interrupt | Design + prototype a non-linear replay: an interrupt/guard mechanism so a mid-scrape reCAPTCHA pauses the plan, runs a discovery/recovery sub-flow (VoidCrawl MCP → fixture, or cached humanized-click recipe), then resumes. Test by hammering Google search ~30× until reCAPTCHA fires. |
| **W2** | #4 | Single hardcoded profile; no IP-vs-profile attribution | Profile-cascade primitive in Yosoi/VoidCrawl wrapper: pin N Chromium profiles, cascade on block, and an experiment that isolates whether blocking is per-IP or per-profile on Google. |
| **W3** | #6, #7 | Teleport double-load + slow; no geocoding | Fix teleport double-load; integrate `geopy` for lat/long; measure Google/Bing/Brave SERP latency and make multi-engine viable. |
| **W4** | #8 | API ergonomics for steps 2–3 of the pipeline | Answer: what should the replay/discovery API look like for the SERP→authority pipeline; enumerate scaling risks (teleport timeout, antibot in hotpath, non-determinism, multi anti-bot tabs). |
| **W5** | #1, #2 (low) | Contract→ODM portability; redundant contracts | Answer/design: cleanly compile a Yosoi data contract to a Mongo/Beanie/Django-Ninja model without plugins; express redundant contracts that differ only by docstring. |

Out of scope: **DataForSEO** (`step2_dataforseo.py`) — paid API, not a scraping problem.

## Definition of done (per workstream)

- A **fix** lands as a focused Yosoi diff with a regression test, **or**
- An **answer** lands as a short written finding (mechanism design, measurement, or
  reasoned defer with a `# FUTURE(CAS-xx)` marker at the real chokepoint).
- The dogfood proof: the corresponding `nimbal/core/web/_real.py` path is rewritten to go
  *through Yosoi* and shown working on the live target.

## Working agreement

- Worktree-isolated; no other autonomous agent edits this branch (per CLAUDE.md).
- `uv run poe ci-check` green before any commit.
- Small focused diffs; defer with `# FUTURE` notes rather than broad rewrites.
- Anti-bot targets are scraped for **our own** SEO/SERP research; respect rate limits and
  never auto-solve captchas — surface and rotate (VoidCrawl MCP guidance).
