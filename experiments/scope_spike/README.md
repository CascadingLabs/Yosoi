# Spike: reuse-scope canonicalization (CAS-83 / CAS-85 / CAS-102)

**Question this spike answers with real data:** when Yosoi learns selectors on one
page of a site, *at what scope* do those selectors safely reuse — and is that scope
the same for every site, or does it depend on what the site offers?

## The model under test

A recipe's **reuse scope** is not declared at discovery; it is a property of the
site. We hypothesize a ladder of stability signals, strongest-available-wins,
every reuse **confirmed by a verify gate** (so a wrong guess costs a re-discovery,
never garbage):

| Tier | Stable signal | Reuse scope | Probe site |
|------|---------------|-------------|-----------|
| 1 | in-page `data-*` / `data-testid` hooks | **domain-wide** | finance.yahoo.com |
| 2 | URL route template (`/r/{sub}/{sort}`) | **per route** | old.reddit.com |
| 3 | structural / AX fingerprint | **per component/page-class** | google.com/maps |
| — | none / one-off | **island** (n=1) | (default floor) |

Decoupled concerns (key architectural decision from the design thread):
1. **Get THIS page right** — single-pass discovery + verify. First-class, always.
2. **Does it reuse, at what scope** — passive, opt-in, *future* layer. Never issues
   its own fetches; only piggybacks organic traffic. Off by default (`reuse="oneshot"`).

## Methodology (per tier)

1. **Seed**: derive a selector set from ONE page only.
2. **Lock** those exact selectors. Apply unchanged to:
   - **must-transfer** siblings (same template / type) — expect clean extraction.
   - **must-refuse** pages (different template, same domain) — expect empty/garbage,
     which proves the cache key must distinguish them (the CAS-83 leak guard).
3. **Score**: transfer = matched>0 AND ≥4/5 fields populated with sane values.

Selectors are derived from the seed page ONLY, then frozen — so the transfer
measurement is unbiased once fixed. Discovery acts as the oracle; transfer is the
thing under test.

## Results

Raw per-tier data in `results/{reddit,yahoo,maps}.json`. Synthesis in
`SPIKE_REPORT.md` (repo root of this worktree's spike dir).

Probes executed via voidcrawl (stealth headless Chrome). Blocked/captcha'd fetches
are reported as data, not hidden.
