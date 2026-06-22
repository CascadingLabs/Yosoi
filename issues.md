# PR status: full_crawl_v2 fingerprint accuracy review

Reviewed staged local state and generated `.yosoi/full_crawl_v2` artifacts after exemplar-based ranking landed.

## Verified

- `uv run pytest tests/unit/examples/test_qscrape_full_crawl_v2.py -q` → **6 passed**.
- `uv run ruff check examples/qscrape.dev/full_crawl_v2.py examples/qscrape.dev/_fingerprint_plan.py tests/unit/examples/test_qscrape_full_crawl_v2.py` → **passed**.
- `uv run mypy examples/qscrape.dev/full_crawl_v2.py examples/qscrape.dev/_fingerprint_plan.py tests/unit/examples/test_qscrape_full_crawl_v2.py` → **passed**.

## Artifact check

- `.yosoi/full_crawl_v2/frontier_urls.json`: **255** URLs.
- `.yosoi/full_crawl_v2/fingerprint_scores.json`: **32,640** rows = unordered all-pairs including self.
- `.yosoi/full_crawl_v2/fingerprint_target_plan.json` now reports:
  - `plan_kind`: `validated_fingerprint_exemplar_ranking`
  - `evidence_scope`: `validated_fingerprint_exemplars`
  - `contract_specific_ranking`: `true`
  - `verified`: `false`

## Accuracy assessment

Accuracy is much better now. The plan is no longer neutral identical fanout. Each contract has different top targets, and they line up with qscrape labels:

- `NewsArticle`: `l3/news/article/MHH-*`
- `ProductContract`: `l3/eshop/product/VM-*`
- `ScoreContract`: `l1/scoretap/match/`, `event`, `team`
- `TaxInfo`: `l3/taxes/viewer/26-*`

This is the right shape: all-page fingerprint similarity audit plus contract-specific exemplar ranking.

## Remaining concerns

1. **Docstrings/comments still describe the old neutral mode.**
   - `examples/qscrape.dev/full_crawl_v2.py` headline says `frontier → neutral candidates → optional verified scrape`.
   - `_fingerprint_plan.py` module docstring still says cold-start neutral fanout and “future validated warm-reference support,” but validated exemplar support now exists.
   - Update wording to say: default demo uses explicit qscrape exemplar URLs for contract-specific fingerprint ranking; fallback/no-exemplar mode remains neutral.

2. **Exemplar labels are still explicit qscrape supervision.**
   - This is fine for an example, but be precise: accuracy improved because we introduced validated exemplars, not because cold-start fingerprints can infer contract intent.
   - Keep artifact metadata honest: `verified=false` still means ranking is not extracted-data success.

3. **Score scale may be saturated.**
   - Many top rows score `1.0` for News/Product/Tax.
   - That may be correct for repeated templates, but tie-breaking then controls ordering. If output quality matters, expose tie-break fields clearly (`exemplar_margin`, support ratio/top3 mean are already a good start).

4. **ScoreTap ranking may be broader than the contract.**
   - Top ScoreContract includes match/event/team pages. Depending on intended contract semantics, event/team may be useful or may be false positives for match/standings extraction.
   - Verified scrape should be the gate here; if too many fail, narrow exemplars or split ScoreTap contracts.

## Recommendation

Keep this direction. Rename docs from “neutral candidate fanout” to “validated exemplar fingerprint ranking,” and make the neutral mode explicitly a fallback/diagnostic mode.
