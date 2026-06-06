# P6 — `ys.policies`: config decisions that affect the pipeline (the pattern)

_Deferred to P6. Tracked on Linear as [CAS-168](https://linear.app/cascadinglabs/issue/CAS-168).
This doc is the thinking; the ticket is the work item._

## The problem it generalizes

A growing set of decisions change *how the pipeline behaves* without changing *what the contract
means*. Today each is an `os.environ` read scattered deep in the call stack:

| decision | today | read where |
|---|---|---|
| serve atoms at all | `YOSOI_ATOM_READS` | `core/atom_read.atom_reads_enabled` |
| which trust tiers serve | `YOSOI_ATOM_TRUST` (strict/yellow) | `core/atom_read.atom_trust_mode` / `allowed_sources` |
| fingerprint signal lane on/off, priority, backpressure | *(not built)* | — |
| reuse similarity thresholds | hard-coded constants | `fingerprint.py` |
| L3 enablement, drift-action thresholds | *(future)* | — |

This violates the CAS-119 purity contract (`resolve()` must be pure — inputs explicit, no global
state) and scatters one concern across many sites. Each new knob adds another env-read and another
buried conditional. The reviews already flagged the narrow version (a `TrustPolicy` value object);
**`ys.policies` is that generalized into a pattern.**

## The pattern: resolve once at the edge, thread an immutable value inward

A **`Policy`** is a frozen value object holding every pipeline-affecting decision. It is **resolved
once at the API edge** (when a scrape/session/contract starts) and **threaded explicitly** through
the pure core. Nothing in `resolve()` / `pipeline` / `atom_read` ever reads the environment again.

```python
class FingerprintPolicy(BaseModel, frozen=True):
    execution: Literal['inline', 'background', 'off'] = 'background'  # signal lane
    backpressure: Literal['defer', 'drop'] = 'defer'   # never blatantly drop (see below)
    priority: Literal['low', 'normal'] = 'low'

class Policy(BaseModel, frozen=True):
    atom_reads: bool = False                 # default-deny
    trust_tier: Literal['strict', 'yellow'] = 'strict'   # quarantine fingerprint-tier by default
    reuse_skeleton_threshold: float = 0.40
    reuse_semantic_threshold: float = 0.50
    fingerprint: FingerprintPolicy = FingerprintPolicy()
```

### Precedence — a cascade (like CSS / git config)

```
defaults  <  env  <  session  <  contract  <  call-site override
```

Each layer is a *partial* override; `Policy.resolve(*layers)` merges into one **effective** Policy.
This is the generalization the pattern buys: **one resolution point, one precedence order, one place
to test.** A new knob is a new field — never a new env-read site, never a new scattered `if`.

### Scope (per the design conversation)

- **Global default** — shipped, **default-deny**: atom_reads off, trust strict, fingerprint signal
  *on but background + low priority*.
- **Per-session** — a run/`Session` carries a `Policy` (e.g. an operator enables `yellow` for a batch).
- **Per-contract** — a `Contract` may pin overrides (e.g. *this* contract opts into fingerprint reuse).
- **Per-call** — ad-hoc override on `ys.scrape(..., policy=...)`.

## The signal-lane sub-policy (resolves the "don't drop it" instruction)

The fingerprint/health work is content-derived but response-independent → it forks off the critical
path. Correction to an earlier sketch: under backpressure it is **deferred as low-priority background
work, NOT dropped** (`backpressure='defer'` default). It enters a bounded low-priority queue drained
by a single worker (the sole writer of the atom's health EWMA, so no contention with the response
path). `drop` is available but opt-in, for the operator who truly wants nothing but throughput.

- **Gathering** the signal is always on (default-on, invisible, off the hot path).
- **Acting** on the signal (reuse, quarantine, re-mint) is policy-gated and default-deny.
- The single scraper who "doesn't know they need it yet" pays nothing and is silently protected from
  silent-corruption; the day they opt into reuse, the history is already populated.

## Why this is the right seam (not just a config bag)

The CAS-119 purity contract *forces* it: `resolve()` must be pure, so configuration must **arrive as
a value, not be read from the world.** `ys.policies` is the single seam where "the world" (env,
session, contract, call) is collapsed into one immutable value at the edge, after which the core is
a deterministic function of `(spec, html, cache, policy)`. That is also what makes behavior
reproducible and unit-testable: pass a `Policy`, assert the path taken.

## Relationship to P5 and sequencing

- **P5** = the fingerprint *behavior*: wire `PageFingerprint.similarity` into the read path + the
  health/drift signal lane.
- **P6** = `ys.policies`: the config *pattern* that governs P5's knobs cleanly.
- The **`TrustPolicy` value object is the MVP slice of P6** and is the natural first step when wiring
  similarity into reads (it removes the env-reads that would otherwise multiply). So P6 can start
  thin (collapse the 3 existing env-reads into `Policy`, threaded from the edge) and grow as P5 adds
  knobs — rather than landing as one big abstraction.

## Acceptance sketch (for the ticket)
1. `yosoi/policies.py`: frozen `Policy` + `FingerprintPolicy`, `Policy.resolve(*layers)` cascade.
2. Replace `atom_reads_enabled` / `atom_trust_mode` / `allowed_sources` env-reads with `Policy`
   fields; thread `policy` from `api.scrape` → `resolve` → `_try_atom_reads`. `resolve()` stays pure.
3. Per-contract override surface (Contract carries an optional `Policy` partial) + per-call `policy=`.
4. The bounded low-priority signal-lane queue + single-writer health drainer (defer-not-drop).
5. Tests: cascade precedence, default-deny, purity (no `os.environ` in core), backpressure=defer
   keeps the reading, fingerprint-tier quarantined under strict.
