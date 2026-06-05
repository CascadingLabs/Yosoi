# FINDINGS — hotpath-dogfood spike

Generated from workflow `wgtj8syf2` (5 investigators → 5 adversarial verifiers, grounded in live Yosoi + Nimbal + VoidCrawl).
Every workstream returned **`needs-work`**: the core proposal is grounded, but the verifier found corrections to fold in before implementation. None were `flawed`.

| WS | Kind | Conf | Verdict | Title |
|----|------|------|---------|-------|
| [W1](W1.md) | fix | 0.78 | needs-work | mid-scrape reCAPTCHA as a behavior-tree reaction |
| [W2](W2.md) | answer | 0.74 | needs-work | multi-profile cascade + per-IP vs per-profile block attribution |
| [W3](W3.md) | fix | 0.78 | needs-work | teleport double-load + multi-engine SERP latency + geopy |
| [W4](W4.md) | answer | 0.78 | needs-work | note #8: Yosoi-native SERP→authority replay/discovery API for Nimbal pipeline steps 1–3 |
| [W5](W5.md) | answer | 0.82 | needs-work | contract→ODM export + description-disambiguated redundant contracts |

---

## Synthesis — cross-cutting learnings (what to actually do)

**The hidden step zero: `execute_plan` is unwired.** Both W1 and W4 found that `yosoi/core/replay/runtime.py:execute_plan` is latent — nothing on the VoidDriver replay lane actually calls it yet. "Forcing Yosoi onto the hotpath" therefore *starts* with wiring `execute_plan` into `_VoidCrawlFetcher`/DOMLoader (behind a flag), **before** any behavior-tree work. This is the single highest-leverage move and a prerequisite for W1.

**Captcha detection: don't add an API, use the one already there.** W1's first design assumed it needed `Page.detect_captcha`, but that's not bound on the `PooledTab` Yosoi replays on. W4 found the clean answer: `PageResponse.antibot.challenged` is **already returned by `PooledTab.goto`** (VoidCrawl `_ext.pyi:16,25`). So the behavior-tree trigger (W1) and the fetcher cascade trigger (W2) can both key off that existing signal — no VoidCrawl change required to *detect*. Binding `capture/inject/solve` onto `PooledTab` is only needed to *recover*, and is mechanical (surface as a VoidCrawl wrapper-gap ask, not a blocker). VoidCrawl's real recovery primitive is the humanized click (`solve_captcha`), not an external 2Captcha call — drop that framing.

**Recommended landing order (smallest blast radius first):**
1. **W5 note #2** — 2-line signature change (`__name__` + docstring into the contract signature) → unblocks AdLink-vs-OrganicLink multi-block SERP scraping. Behind a `sig_version` bump so the 30-domain cache goes STALE, not silent-miss.
2. **W3 #1** — teleport-before-first-paint as a `ReplayPlan.teleport` pre-loop field; keep the example.com secure-context proof as *discovery-time* verification (don't delete it — that was a fail-fast softening the verifier caught).
3. **W2** — extend `BotDetectionError` with `identity_id`/`captcha_kind` first (standalone commit), then the profile-cascade in a new `yosoi/core/fetcher/identity.py`; run the per-IP-vs-per-profile isolation experiment to pick the rotation key *before* wiring proxies.
4. **W4** — wire `execute_plan` into the fetcher lane (step zero above) + parameterized `LessonKey` (engine_host/param_keys); template only `act.url`/`act.text` (never `act.script` — brace safety).
5. **W1** — the behavior-tree model (`NodeKind`/`TreeNode` + `ReplayPlan.tree`, additive, `compile()` wraps legacy flat nodes in a SEQUENCE) + `execute_tree`/`ReactionMiss`, with off-hotpath learning patches reusing the A3Node persist/amend pattern. LLM patches the tree off-hotpath; `execute_tree` stays deterministic + LLM-free.

**Sketch bugs to fix when implementing:** W1 — `for attempt in get_async_retryer(...)` must be `async for` (`retry.py:118` returns `AsyncRetrying`). W2 — `order[attempt.retry_state.attempt_number - 1]` indexing is off (attempt_number semantics). W4 — proxy rotation must rebuild the pool/session, not re-acquire a tab (proxy is pool-scoped).

**Invariant status:** no proposal breaches the hard invariants as designed. Watch one latent CAS-87 risk (W1): never let a learned REACTION's recovery subtree carry a model-derived EVAL leaf — keep recovery leaves to the fixed `_RECOVERY_LEAVES` set.
