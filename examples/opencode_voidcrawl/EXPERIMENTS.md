# OpenCode × voidcrawl — experimental log

A running record of what this worktree explored, what held up under live runs, and
where it breaks. Everything here ran against **live Google Maps, headless, no proxy**.

## Thesis

Replace per-run LLM scraping with a **discover-once, replay-forever** loop:
an agent (or a human) discovers a durable action+extraction plan once; thereafter a
deterministic runtime replays it with **no LLM**, and a **verify score** says when the
plan has drifted and needs re-discovery. The LLM's job shrinks from "every run" to
"once per site, plus healing when verify drops."

## Architecture (what we landed on)

- **A3Node primitive** (`yosoi/models/replay.py`) — Assess → Act → Assert. `act.targets`
  is an ordered selector **fallback cascade**; `expect` is the verify signal; `repeat`
  ticks until `expect` holds. Composition over nodes (`ReplayPlan.nodes`) is a flat
  sequence today, swappable for a tree later — we aligned on the *primitive*, not the
  structure.
- **One selector model** (`yosoi/models/selectors.SelectorEntry`, extended for CAS-27)
  — `css | xpath | regex | jsonld | role | visual`. The *same* `SelectorEntry` powers
  action targets **and** extraction. AX `role` (role + accessible name) is the durable
  default; css/visual are fallbacks.
- **Extraction = `FieldSelectors` cascade + a Yosoi coercion type** — no regex on the
  recipe. The selector finds the *node* (by role + name); the field's **type** (`Rating`,
  a small `reviews`/`after_label` coercer) reads the *value* from its text. Any regex
  lives inside the type, like `Rating` already does.
- **AX extraction** (`yosoi/core/fetcher/dom/ax.py`) — `extract_records` (repeating cards,
  scoped per-card via `childIds`) and `extract_one` (single-record detail pages).
- **Executor + verify** (`examples/opencode_voidcrawl/replay_runtime.py`) — runs each
  node (settle → act → assert), tries the click cascade `role → css → visual`, and
  returns a `VerifyReport` (pass rate). **Settling is event-driven**: a node waits until
  its `assess` precondition holds (the SPA's network never idles); `navigate` is the one
  fixed-dwell exception because Maps resolves teleported geolocation with no DOM signal.

## What held up (live, zero LLM)

| experiment | result |
|---|---|
| Teleport-driven Maps scrape (`maps_teleport.py`) | NY/LA/Chicago each 20 distinct, locality-correct shops; **verify 100%** |
| Replay from persisted JSON plan | reloads `role`/FieldSelectors/types, re-runs deterministically |
| **Query generalization** (`generalize_maps.py`) | one plan, 5 categories (guitar/coffee/dentists/hardware/tattoo) — each 20 shops, **verify 100%**, ~all rated. One plan replaces per-query LLM discovery. |
| **Harder: click into detail** (`harder_maps.py`) | first **live** run of the `role→css` click cascade; opened detail panel |
| **Contract generalization** | small 2-field (card) → large 6-field (detail: name/rating/reviews/address/phone/website) — same machinery, different typed `FieldSelectors` |
| Verify as oracle | correctly flagged an under-scroll at **75%** before a fix; 100% after |

## Honest boundaries found

- **`role` alone is ambiguous** when a card has several same-role nodes. `role('image')`
  grabbed the *photo*, not the rating; fixed with a name substring (`role('image','stars')`).
  This is selector-level targeting (like `click_by_role`), not a value regex.
- **`reviews` on the detail panel = None** — the detail rating node reads "5.0 stars"
  without the review count the card had. A field-level selector mismatch, not an approach
  failure.
- **`address`-type fields need a css/xpath fallback** — one `StaticText` among many, no
  distinguishing name. The `FieldSelectors` cascade *has* the slot, but `extract_records`
  currently resolves only `role` entries against the AX tree; css/xpath would resolve
  against the DOM. **AX↔DOM bridge is the main open gap.**
- **`navigate` geolocation timing** has no DOM signal → fixed dwell (the deliberate
  "small sleep" fallback to event-driven settling).

## Next chapter — the breakdown / transfer study (`heal_study.py`, scaffolded)

The verify score is the oracle; the study maps the deterministic↔LLM frontier:

1. **0-shot LLM heal on controlled breaks** *(done — `heal_study.py`)* — corrupt a
   selector (wrong-name / wrong-role / too-generic) so extraction drops, hand OpenCode
   **only the compact AX outline of one card**, ask 0-shot for the repaired role+name,
   re-extract, measure recovery. One browse; all cells in-memory on captured AX nodes.
   **Result:** baseline 21/21; all three breaks healed to 21/21 0-shot (LLM returned
   `role='image' name='stars'` every time). **Confound:** the truncated outline sample
   happened to be an ad card (no rating node visible), yet the model still answered —
   so it leaned partly on its *own Maps prior knowledge*, not just the outline. The
   clean transfer test (step 3) therefore needs a site the model doesn't know, or an
   anonymised outline, to separate "the AX outline is sufficient" from "the model
   already knows this site".
2. **Modulation matrix** — sweep depth × contract-size × site; read `VerifyReport.score`
   per cell to plot where replay holds vs needs an LLM.
3. **Prior transfer, same-domain** *(done — `transfer_study.py`)* — cold 0-shot vs
   primed (a learned `card-outline → role='image' name='stars'` example as one few-shot),
   across a strong (gpt-5.3-codex) and weak (gpt-5.4-mini) model, with a deliberately
   *vague* field description. **Result: all four cells 21/21** — even weak+vague+cold
   healed perfectly; the prior added nothing. **Finding:** on a well-labelled same-domain
   site there is *no headroom* — the AX outline alone is sufficient for 0-shot heal, so
   learned priors are redundant. Transfer value can only appear where cold *fails*: a
   site the model hasn't memorised and/or genuinely ambiguous structure (no telegraphing
   names). That's the cross-domain regime — the next place to look.

Open questions this should answer: at what interaction depth / contract size does pure
replay break? Is a 0-shot LLM enough to heal, or does it need priors? Do learned plans
make future discovery cheaper?

## Cross-domain transaction — qscrape eshop full checkout (`eshop_checkout.py`)

A structurally different site and a much harder task: buy a product **under 100 GS** and
**check out fully** on `qscrape.dev/l2/eshop/` (a mock sandbox; mock card/address). Three
recon subagents mapped it; the e2e agent placed a mock order; the recipe was locked into a
`ReplayPlan` and replayed through our executor.

**Result: 16/16 nodes, verify 100%, order confirmed (`VM-312-505836`), zero LLM.** The flow:
deep-link a `<100 GS` product (`?sku=VM-MIN-001`, Standard Iron Pickaxe 14.50 GS) → Add to
Cart → cart → Proceed to Checkout → fill 10 form fields → Place Order → assert
`strong[data-order-id]`.

**Why it matters — the inverse of Maps.** The eshop is **AX-blind** where Maps was AX-rich:
the product grid and form inputs have no names/ids/labels (the `<main>` AX subtree is empty),
so the durable handles are **css/data-attrs** (`article[data-sku]`, `input[data-label="…"]`);
only the named **buttons** surface in AX. The plan therefore mixes **`role` selectors for
buttons and `css` for fields in one `SelectorEntry`** — validating the unified model from both
ends. Added a robust **`type` op**: sets value on *all* matches via the native setter + input/
change events, handling the site's **duplicated DOM** (off-screen + visible copies) and
framework-**controlled inputs** in one shot. Settling stayed event-driven; the final `wait`
node polls `strong[data-order-id]` as the success assert.

This is the strongest generalization datapoint yet: the same primitive (A3Node + unified
selectors + verify) drives a stateful, transactional, AX-blind site end to end — not just
read-only scraping.

### Recording for marketing (`record_checkout.py`)

Replays the checkout node-by-node, injects a fixed on-page debug HUD after each step
(`● REC · voidcrawl replay · step k/N: <action> [OK]`, removed before the next action so
it never blocks a click), screenshots each frame, and stitches them with ffmpeg into a GIF
+ MP4 (`.yosoi/video/`, gitignored). `HEADFUL=1` watches it live on a machine with a display.

**voidcrawl has no native video/screencast API** — `Page` exposes only `screenshot` /
`screenshot_png` (stills); there's no screencast/record method on any class, nor in the Rust
crates. CDP `Page.startScreencast` (and Chrome video recording) could back a native
`Page.record()` debug API — a worthwhile VoidCrawl feature; until then, screenshot→ffmpeg is
the path. ffmpeg gotcha: full-page screenshots vary in height per step, so frames are
normalised onto a uniform even canvas before the palette filtergraph (which errors on mixed
sizes); the GIF is derived from the uniform MP4.
