# Product-retrieval evidence ledger

Status as of 2026-11-01. This is empirical research code and data; it does not promote a production discovery engine or a new SDK implementation.

## How to read this report

- A row is a repeated configuration trial unless it explicitly says page or shard. Repeated cases from the same captured pages are not independent pages.
- Candidate-value correctness, owner correctness, node localization, projected-string correctness, DOM coordinates, and native Contract acceptance are different outcomes. Do not combine them into one retrieval score.
- Recall@k uses the present-field denominator; absent-field false positives use a separate absent denominator. Null metrics mean there was no eligible denominator.
- Fresh-page annotation was agent-produced from retained source HTML. It is non-blind and is not independent human gold or a live browser DOM.
- The current consolidated-v3 matrix contains 69,144 overlapping table rows across 17 source artifacts. These are not independent samples and must not be summed with their source runs.

## Current evidence matrix

| Workstream | Status and footprint | Evidence and boundary |
| --- | --- | --- |
| Controlled retrieval baseline | Complete: 60 source-derived cases; 166,320 raw rows per encoder, 162,624 after original-seed exclusion; 19 methods plus 3 hybrids; no scorer exceptions | The detailed controlled comparison below uses obj-003–obj-006 only (40 cases). It does not establish cross-site generalization. |
| Baseline Archive replay | Complete for MiniLM and BGE-small | Restored replay exactly reproduced scores, ranks, ownership, and absence metrics. Timing is excluded; replay used no network or embedding inference. |
| Cross-encoder L6/L12 | Complete, controlled sources only | 7,141 unique pairs per model; three pool budgets and two pool builders. Complete-record accuracy is 0 in all 36 reported configurations for each model; this is a bounded controlled result. |
| Projection policies | Complete: 84,240 rows, 14.872 s, no model inference | The exact comparison below uses MiniLM L6, character-ngram reference pool, budget 5, global/controlled, all fields. Value and node hits are listed separately. |
| Native Contract validation | Complete against the installed Yosoi 0.4.0rc1 package from `yosoi-surface-evidence` | 11,400 unique adapter calls; 23,760 pre-schema record keys expand to 47,520 record/schema links; 166,320 report rows, zero report failures. The manifest's `prepared_record_keys` stores the schema-expanded count. |
| Fresh nonsemantic MinHash/tree slice | Partial coverage: 12 fresh source-HTML pages, 23,520 rows | Only the QScrape two-reference group ran. Tree methods emitted 1,008 partial events. This is not the full reference-group or modality matrix. |
| Expanded foreign semantic wave | Complete: 12 fresh pages × 2 encoders × 5,824 rows = 139,776 rows; 24 shards; zero scorer failures | The cohort uses QScrape references against Books to Scrape, Web Scraper, and Scrapeme pages. It is a small non-blind, agent-annotated cohort, not 139,776 independent examples. Metrics below. |
| Witness-v2 evaluation | Complete, on the persisted expanded-wave predictions | An agent reviewed source roles and exact-value support without model rankings; canonical gold and retrieval code were unchanged. This is a second evaluation contract, not a model improvement or independent human gold. |
| Fixed-channel proposal complementarity | Complete cached analysis: 25 fixed policy orders × 5 budgets × 2 encoders; 24 foreign and 12 same-site page/model shards | Foreign MiniLM structure-only budget 5 yields 16/52 proposal hits; structure+lexical budget 10 yields 18/52; structure+lexical+semantic-reference budget 15 yields 21/52 strict and 23/52 qualified. No new inference. |
| Matched same-site reference contrast | Complete: the same 6 target pages per arm, 69,888 rows per arm | Manually supplied same-site/template references versus foreign QScrape references. Host and template remain confounded. The same-site aggregate has 16 budget-exhausted tree-score outcomes, not scorer exceptions; the foreign aggregate has none. |
| Scaling probe | Complete with method limits: 17 one-axis synthetic cases | 10 fully measured, 1 method unavailable, 5 budget/truncation-limited, 1 budget-rejected; 2.920 s CPU and 2.935 s wall. No model/browser calls; no recursive RuntimeContract proof. |
| Structured Product/Offer metadata | Complete source-extraction attempts for 12 retained pages | 8 Product and 8 Offer candidates came from four microdata and four JSON-LD pages; the four Books pages had no Product/Offer metadata. “12 complete” means 12 extraction attempts completed within bounds, not 12 complete products. Exact raw-display and typed amount/currency evidence are separate profiles; neither is a DOM-location result. |
| Consolidated-v3 registry | Complete: 69,144 rows referencing 17 source artifacts | It preserves each source’s denominator and metric basis; overlapping slices, nulls, and partial coverage remain explicit. |
| Representative expanded-shard Archive replay | Complete for one shard only | 49 artifacts (194,202,422 bytes) were restored from native Archive. The MiniLM `books-obsession` foreign shard recomputed 5,824 rows with the expected quality digest; `scoring_ns` was excluded. This does not mean the whole expanded wave was archived. |
| Live layout capture | Eight captures: four pages at two viewports | Stable rendered DOM, current response body, generic boxes/fonts/styles and viewport PNG retained. Each viewport captures 57/211/331/366 elements before eligibility filtering. New coordinates are evaluated in the layout slice below. |
| Layout retrieval and viewport shift | Executed: four source pages at two viewports, 30,720 configured result rows | Geometry/typography, matched DOM/text controls and fixed candidate pools use live role annotations. Results are element localization, with 33 present cross-template trials per condition; same-page shifts are separate from self diagnostics. |
| One versus two references | Executed: same three held-out targets; 17,472 rows per condition | Three new MiniLM one-reference shards; two-reference shards reused. Structural results hit a ceiling; more references did not consistently improve lexical/semantic ranking. |
| Full expanded reference/hybrid matrix | Frozen, not executed | The 72-case, 13-group, 4-profile matrix still has unmeasured reference groups and semantic channels. |

## Native Contract outcome interpretation

The native report separates unique selection outcomes from record/schema link outcomes:

| Level | Native validated | Native issues | Source-binding rejected | Total |
| --- | ---: | ---: | ---: | ---: |
| Unique adapter selections | 6,492 | 642 | 4,266 | 11,400 |
| Record/schema links | 35,948 | 1,952 | 9,620 | 47,520 |

Of the 35,948 record/schema links that passed native validation, 33,698 are labeled `native_valid_but_wrong` by the experiment's follow-on comparison. That comparison includes locator, owner, alias, root, and optional-field alignment. It is not a semantic value-error rate: native Contract validation checks schema/source structure and type/cardinality constraints, not whether a selected value expresses the product fact correctly. Gold labels were not supplied as validator inputs; they are used only after validation for evaluation.

## Controlled-source comparison

Fixed context representation; global retrieval; obj-003 through obj-006 only (40 cases derived from four source pages). Each source is evaluated with lamp, mug, and lamp+mug references. Trial counts are repeated field/configuration measurements, not independent pages.

| Encoder / method | Present field trials | R@1 | R@5 | Correct top-1 including absent | Missing-field false positives |
| --- | ---: | ---: | ---: | ---: | ---: |
| shared / structural_jaccard | 828 | 0.388 | 0.804 | 321/840 | 12/12 |
| shared / simhash64_structure_reference | 828 | 0.402 | 0.804 | 333/840 | 12/12 |
| shared / lexical_char_ngram_cosine_reference | 828 | 0.771 | 0.924 | 638/840 | 12/12 |
| shared / lexical_tfidf_cosine_reference | 828 | 0.668 | 0.864 | 553/840 | 12/12 |
| shared / bm25 | 828 | 0.000 | 0.210 | 0/840 | 12/12 |
| MiniLM / semantic_query | 828 | 0.072 | 0.170 | 60/840 | 12/12 |
| MiniLM / semantic_reference | 828 | 0.524 | 0.774 | 434/840 | 12/12 |
| MiniLM / hybrid_rrf | 828 | 0.058 | 0.395 | 48/840 | 12/12 |
| MiniLM / hybrid_structural_anchor | 828 | 0.308 | 0.891 | 255/840 | 12/12 |
| BGE-small / semantic_query | 828 | 0.014 | 0.033 | 12/840 | 12/12 |
| BGE-small / semantic_reference | 828 | 0.313 | 0.523 | 259/840 | 12/12 |
| BGE-small / hybrid_rrf | 828 | 0.062 | 0.322 | 51/840 | 12/12 |
| BGE-small / hybrid_structural_anchor | 828 | 0.286 | 0.891 | 237/840 | 12/12 |

The tested symmetric unprefixed MiniLM/BGE representations are configurations, not a verdict on cosine similarity or semantic retrieval generally. Query-only semantic similarity performs poorly here; blindly adding it to RRF can hurt ranking. Most methods also emit candidates for deliberately missing fields, so top-k recall cannot replace absence validation.

## Expanded foreign semantic wave and witness-v2

The aggregate has 84 `all` trials per encoder/method in the `annotator_seen_unseen_template` condition: 52 present-field trials, 28 absent-field trials, and 4 unavailable cases. The following are context/global semantic methods; R@k is conditional on the 52 present rows, while false positives are among the 28 absent rows.

| Encoder / method | R@1 | R@5 | Absent false positives |
| --- | ---: | ---: | ---: |
| MiniLM / semantic_query | 0/52 | 1/52 | 28/28 |
| MiniLM / semantic_reference | 1/52 | 7/52 | 28/28 |
| MiniLM / RRF(BM25 + semantic_reference) | 2/52 | 5/52 | 28/28 |
| BGE-small / semantic_query | 0/52 | 0/52 | 28/28 |
| BGE-small / semantic_reference | 0/52 | 2/52 | 28/28 |

Witness-v2 source-review allows separately reviewed normalized-value alternatives (NFKC, collapsed whitespace, case-folding). On the same saved predictions, MiniLM semantic-reference moves from strict 1/52 to qualified 3/52 at R@1, and 7/52 to 9/52 at R@5. BGE-small moves from 0/52 to 2/52 at R@1, and 2/52 to 5/52 at R@5. The review did not inspect model rankings, alter canonical labels, or change retrieval code; these are alternate label criteria, not a model gain.

## Cached proposal-pool complementarity

The producer evaluated fixed channel orders at five candidate budgets against the retained proposal evidence; it did not run new model inference. On the foreign MiniLM cohort, structure-only at budget 5 proposes a strict hit on 16/52 present rows (qualified 16/52), lexical+structure at budget 10 hits 18/52, and structure+lexical+semantic-reference at budget 15 hits 21/52 strict or 23/52 qualified. The 28 absent foreign rows receive nonempty proposal pools, so proposal coverage does not provide abstention or acceptance evidence.

These are proposal-recall counts at budgets of 5, 10, and 15 candidates, not accepted-value accuracy, and budget 15 is three times the baseline top-5 pool. All channel orders were retained rather than selected using gold. Source coordinates and hashes were verified. The analysis cost was 2.019 s CPU for the foreign 24-shard set and 1.055 s CPU for the matched same-site 12-shard set.

On the same-site pool, structure-only at budget 5 and structure+lexical+semantic-reference at budget 15 both propose 26/26 present rows while leaving all 14/14 absent rows with empty pools. Adding semantic-query at budget 15 keeps 26/26 present proposal hits but makes pools nonempty on 14/14 absent rows, with 408 proposals versus 130 for structure-only across 42 trials. Empty/nonempty proposal pools are not accepted predictions or absence truth.

## Matched same-site reference contrast

Both arms use the same six targets (two per site), with 26 present trial rows—including six root trials—and 14 absent rows. Each arm records 69,888 raw rows across 12 shards and both encoders. This is a reference-group contrast on a small agent-annotated corpus; same-site references were supplied manually, and each host has one template.

| Encoder / method | Same-site R@1 / R@5 | Foreign R@1 / R@5 | Same-site absent FP | Foreign absent FP |
| --- | ---: | ---: | ---: | ---: |
| structural_jaccard (same result under both encoder tags) | 26/26, 26/26 | 2/26, 8/26 | 0/14 | 14/14 |
| MiniLM / semantic_reference | 13/26, 22/26 | 0/26, 4/26 | 0/14 | 14/14 |
| BGE-small / semantic_reference | 8/26, 18/26 | 0/26, 1/26 | 0/14 | 14/14 |

The R@ denominators are the 26 present trial rows, including six roots; absent false positives use 14 absent rows. The same-site aggregate's 16 incomplete tree-score outcomes are `budget_exhausted`, not scorer exceptions; selected structural and semantic-reference rows are complete. A structural tie audit found zero score margin on 18 of 26 audited top decisions; deterministic candidate-ID/node-ID tie rules can decide these outcomes. Do not treat the difference as a general same-site advantage independent of host/template.

The absent fields are also missing from the same-site references. Reference-based channels return zero scores without a field reference, so the 0/14 result does not establish an absence detector for new pages.

The full-vector tie audit verifies 84 saved rows across both encoder tags against 42 recomputed structural vectors. With the original alias labels, the observed 26/26 rank-1 hits become an expected 16.15/26 (62.12%) under uniform permutations within exact-score ties; the per-query worst/best bounds are 8/26 and 26/26. At five candidates, expected coverage is 25.43/26 (97.80%), with bounds 24/26–26/26. Canonical-coordinate rank-1 expectation is 59.05%; separately qualified witnesses leave the alias hit probability unchanged here. These are analytical tie-order sensitivities, not estimates of real-world accuracy or one jointly realizable candidate-ID ordering. No scores were perturbed. Zero scores remain abstentions. The retained scorer pass cost 6.077 CPU s / 6.119 wall s; failed setup/evaluation attempts are not included in that pass timing. Full partitions and matching certificates are under `.generated/product-retrieval-same-site-ties-v1/`.

## Node localization versus projected value

In the 84,240-row seed-projection campaign, the controlled slice has 840 trials: 828 present and 12 absent. The exact row below uses Xenova MiniLM L6, `char_ngram_semantic_reference`, pool budget 5, global mode, controlled stratum, all fields:

| Policy | Correct value at top 1 | Correct node at top 1 | Absent false positives |
| --- | ---: | ---: | ---: |
| original_value_ranking | 57/828 (6.88%) | 363/828 (43.84%) | 12/12 |
| projection_restricted_ranking | 293/828 (35.39%) | 293/828 (35.39%) | 12/12 |
| node_rank_then_project | 375/828 (45.29%) | 363/828 (43.84%) | 12/12 |

Node-rank-then-project uses 3,199 projection reads, including 319 extra reads. It returns more exact values than original-value ranking while preserving the same node top-1 count; the exact string is materialized from source projections after ranking. This is not a DOM coordinate win, and the projections came from seed-supported hints. Campaign elapsed time was 14.872 s with zero model-inference calls. The policies use deterministic candidate-ID ties; this differs from the reranker's initial-pool-order tie handling.

## Live layout and viewport conditions

Four newly captured pages were annotated for product heading, displayed purchase price with currency, and DOM stock prose/quantity: 11 present fields and one absent stock field. Each directed cross-template comparison has 33 present and three absent trials over twelve page pairs. The same-page comparisons have 11 present and one absent trial. These share four pages and eleven underlying present facts; they are not 33 independent products. Labels are source-hash-bound, non-blind agent annotations, separate from all older DOM coordinates.

The frozen profile compares six layout variants with eleven matched DOM/text configurations on the same eligible element universe, plus fifteen fixed channel-order pools at candidate budgets 1/3/5/10/15. Geometry uses viewport-normalized boxes; typography uses numerical computed styles and relative font size; parent geometry normalizes against the immediate parent. No selected text, tag, attribute, or ordinal enters the layout similarity. Ordinary DOM/text controls receive their declared evidence. Reference-based methods use canonical seed nodes only. Weights are fixed development choices, not fitted probabilities. Equal-score tie expectations are retained separately.

A separate read-only audit rebuilt every saved summary counter from proposal IDs and labels: all 960 metric groups in each of the four conditions matched, and source/profile/label hashes verified. The condition code identifies distinct page IDs as cross-template; that is correct for these four one-page-per-template fixtures, but is not an automatic template classifier. Raw row `candidate_count` denotes proposal length, not the full eligible universe. The universe sizes are recorded separately in the frozen cases. Qualified witness sets differ by capture (seven wide alternatives, five narrow); canonical coordinates remain the primary comparison.

Canonical node hits at candidate budget 5:

| Method | Wide → wide | Wide → narrow | Narrow → wide | Narrow → narrow |
| --- | ---: | ---: | ---: | ---: |
| Page geometry | 23/33 | 1/33 | 2/33 | 22/33 |
| Page geometry + typography | 21/33 | 3/33 | 6/33 | 23/33 |
| Parent geometry + typography | 12/33 | 13/33 | 12/33 | 13/33 |
| Typography | 13/33 | 14/33 | 13/33 | 14/33 |
| Structural Jaccard | 10/33 | 10/33 | 10/33 | 10/33 |
| Character reference, contextual text | 10/33 | 10/33 | 10/33 | 10/33 |

Wide is 1920×1080; narrow is 390×844. Both use the desktop browser UA, `mobile=false`, and device scale one. This is a viewport/reflow experiment, not mobile-device certification. Qualified alternative witnesses give page geometry 23/33 on narrow→narrow and page geometry+typography 22/33 on wide→wide and 24/33 on narrow→narrow; these are alternate evaluation criteria, not scoring changes. Every present canonical field remains in the eligible universe, so the geometry collapse is a ranking failure rather than missing target candidates.

Even on the same page, geometry drops from 11/11 at a shared viewport to 1/11 across widths. Parent geometry+typography retains 10/11 wide→narrow and 11/11 narrow→wide, while typography alone has feature collisions even in self diagnostics. Normalizing pixel coordinates handles uniform scaling in a unit check, but does not make responsive reflow invariant. The cross-template absent fields still receive nonempty pools in all shown reference methods (3/3); this supplies no absence or acceptance guarantee.

All four viewport-direction runs completed with 7,680 rows each and about 0.98–1.21 CPU s per full analysis, without inference or network. An earlier wide-only analysis cost 1.232 CPU s separately. The updated runner reproduced all 7,680 original wide rows exactly after excluding `scoring_ns`; this is a wrapper replay, not an additional quality sample. Feature preparation, live capture, and unmeasured development overhead are separate costs. The eligible universes have 422 wide and 348 narrow elements. Occlusion is not certified by the eligibility filter: one narrow stock element is present in the DOM but covered by a fixed footer. No Surface-step savings are inferred.

Profiles, copied producers, labels and results are under `.generated/product-retrieval-layout-frozen-{wide,narrow}-v3/`, `.generated/product-retrieval-layout-gold{,-narrow}-v1/` and `.generated/product-retrieval-layout-{wide-to-wide,wide-to-narrow,narrow-to-wide,narrow-to-narrow}-v1/`. The first frozen layout profile was not scored; the original wide-only results used frozen-v2. Viewport scoring uses v3 with unchanged feature formulas, new source binding checks and separate target/seed corpora.

## Matched one-versus-two-reference comparison

The first already-declared held-out target per template was used: Books Sophie’s World, Web Scraper ThinkPad T540p, and ScrapeMe Venusaur. The one-reference set is a strict subset of the two-reference set, and targets are disjoint from both. Context/global results below use 13 present trials including roots, seven absent trials and one external-URL identity per condition:

| Method | One-reference R@1 / R@5 | Two-reference R@1 / R@5 |
| --- | ---: | ---: |
| Structural Jaccard | 13/13, 13/13 | 13/13, 13/13 |
| Character reference | 8/13, 13/13 | 8/13, 12/13 |
| MiniLM semantic reference | 5/13, 11/13 | 5/13, 10/13 |
| MiniLM semantic query | 0/13, 0/13 | 0/13, 0/13 |

Adding a reference can change distractor ranks as well as target scores; it is not a monotonic recall improvement. This small, previously inspected cohort does not choose an optimal reference count. Both reference conditions use the same saved vectors with no new inference. The three new one-reference shard certificates sum to 49.668 s wall; reused two-reference certificates sum to 51.561 s, with different run times/environments and no paired latency repeat. Neither has scorer exceptions; the one-reference condition has no budget-exhausted outcomes, while the two-reference condition has four. Both retain partial tree comparisons separately. Missing-reference fields again explain zero reference-method proposals on the seven absent fields, rather than proving absence detection. Outputs and measured producer snapshots are under `.generated/product-retrieval-reference-count-v1/`.

## Structured metadata evidence

The bounded extractor read only the fresh manifest and saved source HTML. It parsed 12 source pages: four pages had no Product/Offer metadata, four had microdata, and four had JSON-LD. The operator had inspected sample labels before the extraction run, so this is not a blind operator evaluation; the artifact records that limitation. Source HTML cannot establish rendered visibility, freshness, or semantic truth.

Price outcomes are separate string and typed profiles: four Web Scraper microdata `price` strings exactly match the manual display string `$…`; four Scrapeme JSON-LD offers provide numeric amounts with explicit GBP that match the typed canonical amount/currency pair. The `$…` strings are not stripped to manufacture numeric amounts. These are eight page-level price witnesses across two different contract profiles—not eight DOM-location wins. The Books pages have no structured prices. Four `InStock` URIs are enum states, not stock quantities or prose. Color and material were absent from both metadata and manual page labels in all 12 pages.

The profile extracts Product `name`, `sku`, `productID`, `color`, `material`, and Offer `price`, `priceCurrency`, `availability`. It does not fetch remote contexts, execute JavaScript, recover an HTML5 rendered DOM, process `itemref`, traverse `PriceSpecification`, or validate arbitrary Schema.org fields. Per-page pointers, source hashes, node/byte provenance, limits, and exact display comparisons are under `.generated/product-retrieval-structured-v1/`.

## Global embedding preparation cost

There is one shared vector artifact of 16,264 exact strings per model. The 12-page semantic wave, same-site/foreign contrast, and proposal analysis reuse it; they did not each run embedding inference. Each page-shard summary repeats the global preparation ledger. Summing those repeated fields falsely multiplied preparation cost; the table below uses one global ledger per model.

| Model | Vector inputs | Cache hits / newly embedded | Input tokens | Batch calls | Inference CPU / wall | Total adapter / incl. artifact write |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MiniLM L6 | 16,264 | 7,576 / 8,688 | 414,713 | 272 | 212.05 / 214.50 s | 248.20 / 251.44 s |
| BGE-small v1.5 | 16,264 | 3,384 / 12,880 | 734,433 | 403 | 952.82 / 958.52 s | 1,008.02 / 1,011.60 s |

The MiniLM cache includes 4,192 resumed expanded vectors whose earlier computation cost was unmeasured; the other 3,384 cached strings overlap the original set. BGE cache hits are the 3,384 original strings. Both ledgers use local, offline, one-thread inference and direct API cost $0. Hardware/electricity/operator cost is unknown. These costs are global preparation costs, separate from scoring and not attributable again to each page shard or reference arm.

Inputs and cache counts are recorded in `.generated/product-retrieval-expanded-input/preflight-v3-resume.json`; completed batch timings are in `.generated/product-retrieval-expanded-input/{minilm,bge-small}-v1.batches.jsonl`. The full vectors are in the matching `*-v1.json` artifacts. Representative page-shard summaries repeat the same global preparation ledger; they are not separate embedding runs.

## Live layout evidence

The bounded research CDP adapter captured current QScrape `obj-001`, Books `books-obsession`, Web Scraper `webscraper-packard-255-g2`, and ScrapeMe `scrapeme-bulbasaur` at wide and narrow viewports. All eight main responses were HTTP 200, DOM hashes stayed stable across geometry/screenshot capture, and no CDP events were dropped. The screenshots were visually inspected and show the expected product pages. The sandbox remained enabled; owned browser processes reaped and temporary profiles were removed. The adapter source, browser executable hash and WebSocket helper identity were retained before each capture run. The narrow four-page run took 8.384 s wall, separate from the wide 9.038 s.

One Books script failed at each viewport; Web Scraper had one image failure at each, with six wide and five narrow Fetch failures. Capture completion means the declared evidence was retained, not that every subresource loaded. This was regular Chromium 155.0.8059.84 under the repository's regression allowlist, not a new browser/controller certification. The raw CDP adapter does not add a public SDK primitive. No archived gold coordinates were applied to the new DOMs. Outputs are under `.generated/product-retrieval-layout-v1/` and `.generated/product-retrieval-layout-narrow-v1/`; retrieval quality is assessed separately above.

## Limits and remaining research

- The expanded semantic wave is 12 source pages over three templates with QScrape references, not a blind holdout or full 72-case/13-group matrix.
- Same-site reference selection is manually supplied; host and template are confounded.
- Fixed-channel proposal recall is not accepted-value accuracy or a measured reduction in model turns/Surface cost.
- Fresh labels are agent-produced from source HTML, not independent human gold. `witness-v2` changes evaluation alternatives, not source truth.
- The scaling sweep is one axis at a time. Runtime Contract recursion, arbitrary nested optional records, multilingual coverage, full AX/visual/layout evidence, and actual model-turn/Surface savings remain unproven.
- Useful proposals, complete validated outputs, projection reads, and DOM coordinates are separate products and costs.
- No production engine, production SDK, or universal retrieval claim is established.

## Local artifacts

- Baseline matrix: `.generated/product-retrieval-minilm-v3/`, `.generated/product-retrieval-bge-v3/`
- Expanded foreign semantic wave and witness-v2: `.generated/product-retrieval-expanded-semantic-wave-v1/`, `.generated/product-retrieval-expanded-semantic-aggregate-v1/`
- Same-site and matched foreign contrast: `.generated/product-retrieval-same-site-v1/`
- Projection and native validation: `.generated/product-retrieval-projection-v1/`, `.generated/product-retrieval-contract-validation-v1.manifest.json`
- Scaling and structured metadata: `.generated/product-retrieval-scaling-v1/`, `.generated/product-retrieval-structured-v1/`
- Consolidated row registry: `.generated/product-retrieval-consolidated-v3/matrix-manifest.json`
- Cached proposal-pool complementarity: `.generated/product-retrieval-complementarity-foreign-v1/summary.json`, `.generated/product-retrieval-complementarity-same-site-v1/summary.json`
- Representative expanded shard archive replay: `.generated/product-retrieval-expanded-archive-v1/`, `.generated/product-retrieval-expanded-replay-v1/replay-certificate.json`
