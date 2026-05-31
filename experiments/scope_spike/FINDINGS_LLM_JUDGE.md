# Findings: the LLM-judge guard ("you could just *tell* the page was wrong")

**Branch:** `spike/cas-83-scope-canon`
**Run:** `make_judge_packets.py` → 3 parallel Sonnet judges → `score_judge.py`
**Data:** same 13-domain / 52-sample fixtures as the algorithmic run.

## The idea

The algorithms see `cosine 0.993` and say "same page." A human reads the title
**"overview for spez"** at url **/user/spez** and instantly knows it's a profile,
not a listing — wrong page, refuse. That judgment uses signals the threshold
can't access: *what the words mean*. This experiment bottles that as a validation
guard and scores it head-to-head, fair fight.

## Method (no cheating)

- `make_judge_packets.py` emits one packet per replay decision with **exactly what
  the algorithms saw** — seed + replay `{url, title, body_class, rows, top_tags}`.
  Ground-truth labels are **withheld** (kept in a separate truth file).
- Three Sonnet sub-agents judge 52 packets in parallel (cost), each returning
  `{verdict, confidence, reason}`. No agent saw the labels or the other guards.
- `score_judge.py` merges verdicts and scores them in the same confusion frame.

## Result — perfect, on the samples that broke every algorithm

| approach | good ✓ | bad ✓ | **LEAKS** | false alarms | accuracy |
|---|---|---|---|---|---|
| **llm_judge** | **26** | **26** | **0** | **0** | **1.00** |
| structural | 26 | 22 | 4 | 0 | 0.92 |
| card+struct | 21 | 25 | 1 | 5 | 0.88 |
| cardinality | 21 | 24 | 2 | 5 | 0.87 |
| discovery | 24 | 18 | 8 | 2 | 0.81 |
| route | 13 | 19 | 7 | 13 | 0.62 |

**Zero leaks, zero false alarms.** It caught every wrong page *and* allowed every
good transfer — including the cross-language EN/JA Wikipedia categories.

## It nailed the two cases no numeric signal could

1. **The costume case — reddit `/user/spez`** (cosine 0.993 to the listing seed;
   defeated discovery + cardinality + structural):
   > REFUSE (conf 0.97): *"user profile page (/user/spez, title 'overview for
   > spez', body_class 'profile-page', rows=5 of mixed recent activity) — not a
   > subreddit link listing despite sharing the 'listing-page' class."*
   It read the **title and URL**, not the shape. That's the signal a cosine can't have.

2. **The HN 190-row trap** (a comments page with *more* rows than the seed —
   slipped past cardinality's one-sided floor):
   > REFUSE: *"comments thread page (/item?id=…) with a full article headline as
   > title, rows=190 comment rows, and a p/br/font/table explosion — not a story
   > index."*
   It understood that 190 > 30 means *wrong kind*, not *bigger list* — semantics
   the band check structurally cannot encode.

And it did **not** over-refuse the case that fooled the algorithms the other way:
reddit `/r/Python/top` dropped to 5 rows (login-gated stub), which made
cardinality false-alarm — the judge allowed it (conf 0.92) because *body-class and
title say it's plainly the same kind of page.*

## Why this works where thresholds can't

The algorithmic guards classify on **geometry** (how similar are these vectors).
The judge classifies on **meaning** (what kind of page is this). The transfer/
refuse cosine distributions *overlap* — geometry literally cannot separate
`/user/spez` from a listing. Meaning separates them trivially. This is the user's
point exactly: a reader is smarter than a distance metric *on this specific task*,
because page-class is a semantic property the words carry and the shape doesn't.

## The honest caveats (so we don't over-claim a 1.00)

- **n=52.** Perfect here ≠ perfect forever. It's strong evidence the *class* of
  signal (semantic judgment) dominates the *class* of signal (geometric threshold),
  not a guarantee of a 0% error rate at scale.
- **Cost & latency.** An LLM call per replay is far heavier than a cosine. This
  cannot be the *per-page* gate on a bulk run — it would erase the "discover once,
  replay forever, no-LLM" economics that justify the cache.
- **It's still probabilistic** — it's a smarter classifier, not a deterministic
  proof. It returns confidence, not certainty. For the *truly* unkillable case you
  still want a deterministic content invariant where one exists (e.g. "row's
  subreddit == requested subreddit").
- The judges flagged their own soft spot: the EN-Wikipedia seed was a broken
  recipe (1 row) — they correctly called page-*kind* "allow" while noting the
  *selector* is junk. Page-class safety and selector quality are different axes;
  the judge cleanly separated them rather than conflating.

## The synthesis: judge at the boundary, cache the verdict, invariant for the kill

The winning design isn't "LLM every page" (too slow) or "threshold every page"
(leaks). It's **tiered**, and the judge's role is precise:

1. **Cheap structural prefilter (free, every replay):** cosine + two-sided
   cardinality. Auto-allow the obvious-same, auto-refuse the obvious-different.
   This is routing, not safety.
2. **LLM judge at the *boundary* (rare):** only when the prefilter is uncertain
   *or* when promoting a new page-class for a domain the **first time**. The judge's
   verdict is **cached per page-class signature** — so you pay the LLM once per
   *kind* of page, then replay free. This preserves the no-LLM-replay economics
   while buying the judge's accuracy exactly where it matters.
3. **Deterministic content invariant for the kill (where one exists):** when the
   contract can declare "row.subreddit == requested" or "row.symbol == requested",
   that's a fail-closed proof with no threshold and no LLM — strictly better than
   either, and it's the final backstop for the costume case at bulk scale.

So the layering, finalized by the data:
**structural prefilter → (boundary) LLM judge, cached → (kill) deterministic
invariant.** The judge is the *cold-start page-class oracle*, not the hot-path gate.
That's how "the model can just tell it's wrong" becomes affordable: judge once per
page-class, cache the call, fall back to a hard invariant for the adversarial tail.

## Files
- `make_judge_packets.py` — builds label-free judge packets + truth file.
- `score_judge.py` / `inspect_judge.py` — scoring + edge-case inspection.
- `results/judge_packets.json`, `judge_truth.json`, `judge_slice_{0,1,2}.json`,
  `judge_verdicts_{0,1,2}.json`, `judge_score.txt` — the run.
- Compare: `FINDINGS_MULTIDOMAIN.md` (the algorithmic shootout this beats).
