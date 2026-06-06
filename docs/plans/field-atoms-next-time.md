# Field-atom redesign — state of play & plan for next time

_Branch `andberg9/field-atom-index` (worktree `../yosoi-field-atoms`). Written 2026-06-05 at the end of
the overnight edge-case hardening loop. The active spike (`spike/hotpath-dogfood`) was left untouched._

## Where we are

P0–P4 of `take-five-sub-agents-of-sharded-petal.md` are **done and green** (~1702 unit tests), plus the
provenance/trust tiers and the first slice of P5 (the waterfall fingerprint, L1+L2):

| Phase | State | Identity / behavior |
|-------|-------|---------------------|
| P0 canonical contract identity | ✅ | name+doc folded into `spec.fingerprint`; AdLink≠OrganicLink |
| P1 `page_shape_fp` | ✅ | `s1:` tag-histogram bucket, degenerate sentinel |
| P1.5 discrimination gate | ✅ | `mutually_discriminated` gates internalize |
| P2 field-atom store (dual-write) | ✅ | atom key = `(page_shape, region_role, field, yosoi_type)`; domain→provenance |
| P3 flag-gated atom reads | ✅ | `YOSOI_ATOM_READS`; exact-shape + unambiguous only, fail-closed |
| P4 scheme `a1` + `list_stale_by_scheme` | ✅ | non-destructive migration substrate |
| Provenance / trust tiers | ✅ | `AtomSource` verified>manual/llm>fingerprint; `YOSOI_ATOM_TRUST` strict default quarantines `fingerprint` |
| P5 fingerprint L1 (skeleton) + L2 (semantics) | ✅ | `PageFingerprint.of(html).matches(...)`, conjunctive fail-closed; thresholds 0.40/0.50 tuned on 12-page live sweep |
| P5 L0 (static tag tag) | ⏭ out of scope | not wired (user: "L0 isn't wired yet") |
| P5 L3 (network/interaction/cookies) | ⏭ not built | needs FetchResult/CDP plumbing — see below |

### Edge-case hardening loop (5 rounds, this session)
1. **Round 1** (`c1e9a1b`) — `PageFingerprint.degenerate` guard so two thin pages never match; `AtomSource`
   `Literal` + `_selector_has_value` validator + `min_length=1` on key parts.
2. **Round 2** (`8f96688`) — `is_degenerate_shape(':degenerate')` guard at every serve/internalize seam
   (`resolve_via_atoms`, `_internalize_accepted`).
3. **Round 3** (`d2fd3ff`) — **no silent degradation**: one corrupt/outdated JSONL line used to crash the
   _whole_ `AtomStore` load → every atom read silently dead. Now `_load` skips bad lines with a WARNING;
   upsert conflicts and the resolve fallback log instead of swallowing.
4. **Round 4** (`3d7bbbe`) — readability: module orientation map in `fingerprint.py` (three views, cheapest
   first; point callers at `PageFingerprint`).
5. **Round 5** (this doc) — final edge sweep: confirmed matcher **symmetry**, **content-volume invariance**
   (degenerate guard correctly refuses thin pairs), and **empty-`requested`** is already defended in
   `_try_atom_reads`.

## Known sharp edges still open (start here next time)
- **`yosoi_type=None` vs `''` collide in the atom key** (`atoms.py:112` `self.yosoi_type or ''`). Harmless
  today (None dominates) but it's a latent key collision. Decide a canonical sentinel.
- **Cross-shape reuse is still all-or-nothing.** P3 serves only on an EXACT `page_shape_fp` match. The
  `PageFingerprint` similarity path (L1/L2) exists and is validated but is **not yet wired into the read
  path** — atoms can't yet ride from one shape bucket to a similar one. This is the headline P5 read win and
  is gated behind the `fingerprint` trust tier (default-quarantined) for exactly the right reason.
- **Trust policy is read from env at three call sites** (`allowed_sources`, `atom_trust_mode`,
  thresholds). The libertarian/dictator reviews both wanted these collapsed into one `TrustPolicy` value
  object threaded from the edge, instead of `os.environ` reached deep in `resolve`. Pure-function purity says
  the same.
- **L2 semantics recursion** (`_ld_types` over JSON-LD) has no depth guard — a pathologically nested
  schema.org blob could recurse deep. Low risk, cheap to cap.

## Inspiration from the other worktrees
- **`Yosoi-spike-hotpath/yosoi/storage/a3node.py` — A3Node "DOM-stability recipe."** Per-domain, persists the
  _sequence of actions_ that reached page stability so a replay can skip the probe phase. This is the missing
  **P5 L3 substrate**: an atom for a JS-rendered page (Yahoo cross-ticker) needs not just a selector but the
  interaction/settle recipe that makes the selector resolvable. Next-time L3 = attach an A3Node-style stability
  recipe reference to the atom (keyed by shape, not domain), so the field-atom and the stability recipe are one
  record seen from two ends — exactly the "query planning vs query admission" duality in the P0 plan.
- **`needs_discovery.py::contract_fingerprint`** in the hotpath lane mirrors our `spec.fingerprint` — keep the
  two from drifting when this branch merges back.

## Suggested next session (in order)
1. **TrustPolicy value object** — collapse the three env reads into one immutable policy threaded from the API
   edge into `resolve`. Pure, testable, unblocks everything below. (Small, do first.)
2. **Wire `PageFingerprint` similarity into the read path** behind the `fingerprint` trust tier: on an
   exact-shape miss, look for atoms in a _similar_ shape (skeleton≥0.40 ∧ semantic≥0.50), serve only under
   `YOSOI_ATOM_TRUST=yellow`, stamp the served atom `source='fingerprint'`. This is the cross-shape reuse the
   whole redesign is for; it stays default-quarantined.
3. **P5 L3** — plumb `FetchResult` (network trace + cookie/auth state + A3Node stability recipe) into the
   fingerprint and onto the atom, so JS/auth-gated pages become cacheable. Borrow `a3node.py` wholesale.
4. **Gated atom-primary flip** (the risky half of P4): only after the live SERP case passes repeatedly in
   prod — flip reads to atoms-first, demote the legacy lesson cache to fallback.

## Guardrails that must not regress
- Fail-closed everywhere: ABSTAIN→discover, never guess a selector across a similar-but-not-equal shape.
- Never lose the provenance signal (`source`); never serve a `fingerprint`-tier atom under strict.
- Degenerate pages never mint and never serve.
- Scheme-versioned, non-destructive migration; never trust the index over the live SSoT.
- One owner per branch; the spike stays untouched.
