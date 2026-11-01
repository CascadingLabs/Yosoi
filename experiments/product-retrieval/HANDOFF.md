# Fingerprint spike handoff — 2026-11-01

## Disposition

Andrew deferred fingerprinting: it is not needed immediately. Stop experiments,
model calls, implementation, and CI repair. Preserve the work on **draft PR #178**,
separate from the Surface/Session implementation stack. Do not merge or close the
draft as part of this checkpoint. The broad research goal is paused, not achieved.

If resumed, use the findings to shape a fresh `ys.fingerprint` implementation;
do not promote this research code into the SDK. The previously discussed base was
above #170 on the #183/#177/#170 stack; resolve the actual stack at that time.
Discovery remains a separate future consumer of Archive, Contract, Surface and
Fingerprint. No discovery engine or production fingerprint API was delivered.

## Read first

- [Experiment map and reproduction boundaries](README.md)
- [Detailed results through the viewport/reference-count slice](results-initial.md)
- [Measured/partial/unmeasured inventory](measured-matrix.json)
- Original spike: [contract-fingerprints](../contract-fingerprints/README.md)
- Closeout: CAS-646. Future substrate: CAS-647, CAS-648, CAS-649, CAS-652.
- Future consumers: CAS-634 suggestions, CAS-650 discovery, CAS-651 model review.
- Other research: CAS-638 mutations and CAS-633 article transfer.

This note includes the final model-review and pool-ablation results that were
completed after the detailed ledger's last narrative update. It supersedes older
notes proposing immediate implementation or closing the research PR.

## Findings worth carrying forward

| Finding | Evidence | Implication / limit |
| --- | --- | --- |
| Structural reuse is useful within a template | Matched six-page same-site comparison: 26/26 present decisions at rank 1 versus 2/26 with foreign references; six decisions are roots | 18 top decisions were tied. Original-alias uniform-tie expectation is 62.1% at rank 1 and 97.8% within five candidates. This supports shortlisting, not automatic acceptance. |
| Cheap lexical features were strong controls | Controlled context/global slice: character-reference R@1 638/828 (77.1%), MiniLM reference 434/828 (52.4%), structural Jaccard 321/828 (38.8%) | Controlled source-derived cases; not cross-domain reliability. Embeddings, SimHash and cross-encoders are not universal upgrades. |
| Separate node localization from value projection | L6 controlled pool-5 slice: original 57/828 correct values; node-rank-then-project 375/828, with unchanged 363/828 node hits | Seed-supported projection reads recover values without improving localization. No new inference; no absence guarantee. |
| Layout can help and then fail sharply | Geometry canonical R@5 across different templates: 23/33 wide→wide, 1/33 wide→narrow, 2/33 narrow→wide, 22/33 narrow→narrow | Four pages, two viewports. Normalized coordinates do not make responsive reflow invariant. Parent-relative geometry/typography was steadier but weaker overall. |
| Additional references can worsen ranks | Matched three-target experiment: character R@5 13/13→12/13 and MiniLM-reference 11/13→10/13 with one→two references; structural stays 13/13 | No optimal reference count established. Same targets, nested seed sets, saved vectors; timing occasions differ. |
| Mixing channels has a budget cost | Cached top-five pool ablation: wide→wide geometry alone covers 23/33 canonical fields at output budget 5; layout→lexical covers 24/33; structure→lexical→layout covers 15/33 | Order and budget allocation matter. The triple reaches 26/33 at budget 15. These are proposal pools, not accepted values. |
| Scope and acceptance are separate | URL-policy matrix covers same-page/host/origin/registrable-domain variants with PSL/private-domain and IDNA cases | Eligibility is not resemblance, semantic truth, or live-action authority. No final serving scope was selected. |
| Structured metadata is another evidence channel | Twelve source pages yield eight Product/Offer candidates; four exact displayed-price strings and four separate typed GBP amount/currency witnesses | Not eight DOM-location wins. Availability URI, prose and quantity remain different value kinds; missing metadata does not prove absence. |

## Source-grounded model review

One configured model, `deepseek/deepseek-v4-flash`, reviewed the same frozen pools
with selected text, nearby DOM, or retained document-element context. Four narrow
captures, two repetitions and three evidence views produced **24 real requests**.
No tools, new selection generation or discovery were allowed. The 210 unique
proposals include 10 qualified witness candidates covering 9/11 present fields;
two fields are unreachable from this pool even with a perfect validator.

| Evidence view | Strict witness precision, repeats 0 / 1 | Correctly accepted fields, out of 11 | Charge for eight requests | Median HTTP round trip |
| --- | --- | --- | --- | --- |
| Selected text | 4/7, 7/11 | 4, 7 | $0.01175024 | 20.63 s |
| Nearby DOM | 8/9, 9/12 | 7, 8 | $0.017416698 | 41.27 s |
| Document elements | 9/12, 9/11 | 8, 8 | $0.027663104 | 49.43 s |

Total provider-reported charge: **$0.056830042**. Overall median HTTP time was
37.25 s; the observed maximum was 65.68 s. These were bulk batches of 49–56
proposals per page, not a tested quick-look policy. Hosting varied between
Parasail and DeepInfra, caching differed, and two repetitions are not population
latency evidence. The separate Codex/agent token cost is **not** included here.

All 24 outputs passed the structured response protocol. Schema validity and
literal citations still do not establish correct role, ownership or projection:

- The 16 supported non-witness events group into breadcrumb/name-role mistakes
  and labeled price/availability rows containing the right fact but needing a
  narrower projection. Do not call all of these factual semantic errors.
- One broad, truncated price table was correctly denied by the separate source
  completeness guard, despite a model-supported verdict.
- One valid h1 was denied because `E000042` and `selected:P004` were different
  handles for the **same node**. Normalize underlying source identity rather than
  treating handle spelling as a semantic distinction. Primary metrics above are
  preserved under the frozen strict-ID policy.
- Six qualified-positive rejections judged a price against the name/heading
  contract. Field-task binding in batched review needs investigation; adding
  context alone did not fix it.
- No wrong-product/fact group was found in the targeted error audit. This does
  not prove universal factual accuracy: the task is a closed candidate review
  on a small, non-blind public-shop corpus.

Nonempty-string acceptance would accept all 210 proposals (10 qualified positives,
200 coordinate negatives). The untruncated-only gate accepts 188 (10 positives,
178 negatives). These are simple baselines, not fresh native RuntimeContract
extraction runs. Insufficient evidence is abstention; no-accept is not always a
false factual assertion.

## Contracts and SDK shape

Carry forward source/profile versions, capture context, component correspondence,
raw channel scores, budgets, ties, missing/unsupported evidence and failure reasons.
Keep node selection, projection, role/fact correctness, native validation and live
action authorization distinct. Preserve useful partial evidence on failure.

The proposed module responsibility map is recorded in CAS-648: public profile,
model, comparison and policy types; internal extraction/comparison; existing
Archive boundary; equivalent Rust/Python semantics. No new Cargo package was
chosen. Locator fallback execution, model review and repair belong to downstream
consumers, not the fingerprint core. Weighted Jaccard is feature overlap, not
semantic understanding; hashes/sketches compress evidence rather than create it.

## Evidence and replay

Code and notes are committed. Large vectors, captured page bodies, screenshots,
provider prompts/responses and generated reports remain private under `.generated`
in `/home/andrew/Desktop/cl/yosoi-product-retrieval-matrix`; they are not available
merely by cloning this PR. Preserve that workspace before cleanup. Do not refetch
live URLs and assume the same evidence. No credentials belong in a handoff bundle.

| Local path under `.generated/` | Contents / proof |
| --- | --- |
| `product-retrieval-consolidated-v4/` | 74,855 overlapping table rows from 19 artifacts; CSV, source hashes, producer. Not independent samples. |
| `product-retrieval-{minilm,bge}-v3/` and corresponding replay folders | Two completed baseline runs, 166,320 rows each, and exact matching replays. |
| `product-retrieval-expanded-semantic-wave-v1/` | 24 completed foreign-reference page/model shards. |
| `product-retrieval-same-site-v1/`, `product-retrieval-same-site-ties-v1/` | Matched source contrast and exact full-vector tie audit. |
| `product-retrieval-reference-count-v1/` | One/two-reference paired conditions and preserved measured producers. |
| `product-retrieval-layout-{wide-to-wide,wide-to-narrow,narrow-to-wide,narrow-to-narrow}-v1/` | Four viewport conditions; copied frozen profiles and separate source-bound labels. |
| `product-retrieval-layout-pool-ablation-v1/` | Complete immutable 68,160-row proposal gzip and run plan. Original summary stage failed. |
| `product-retrieval-layout-pool-ablation-v2/attempt-3-field-hits/` | Recovered evaluation, 5,680 groups. Distinguishes any-field hit from fractional witness coverage. Earlier failed attempts remain preserved. |
| `product-retrieval-review-{frozen,responses,evaluation}-v1/` | All 24 request/response receipts, immutable inputs, primary evaluation and costs. |
| `product-retrieval-review-{pool,error}-audit-v1.json` | Independent input/count audit and error taxonomy; no gold retrofitting. |
| `product-retrieval-review-{archive,restored,replayed}-v1/` | 152 artifacts / 6,155,975 raw bytes round-tripped through native Archive. Evaluation summary and decision digests match exactly, with network blocked and zero new inference. |

The model replay re-evaluates cached responses. It does **not** regenerate
stochastic provider inference. Original baselines also have actual recomputed
matching proofs; expanded matching replay covers one representative 5,824-row
shard, not every expanded shard. Producers are versioned/captured; later formatting
or recovery code does not retroactively change a measurement's source identity.

## Validation and stop boundary

- Last completed local experiment suite: **246 tests and 62 subtests passed**.
- Installed native SDK evidence used Yosoi **0.4.0rc1** from the
  `yosoi-surface-evidence` checkout, not a fresh build of this PR or #170.
- Original PR head `5635c7f4` already had strict Clippy failures in Rust spike tests
  and Python/browser failures. No hosted-CI-green claim is made for this checkpoint.
- A closeout Cargo check was interrupted at Andrew's request. Its unfinished
  CI-only test edits were reverted. Do not report that check as passed.
- No more experiments, builds, paid inference or CI repair are authorized by this
  handoff. Keep the draft unmerged; revisit only when fingerprinting is prioritized.

## Outstanding work and dispositions

All implementation/research follow-ups are deferred, not proven unnecessary or
completed: arbitrary nested Contracts/root ownership; optional/repeated branches;
fresh independent real templates; multilingual and temporal/value drift; learned
HTML/visual/AX representations; calibrated acceptance/routing; and actual total
discovery-turn/Surface-step savings. The declared 72-case/13-reference-group matrix
was not fully executed. URL scope choices and recursion limits remain open.

CAS-633 is separate local article/linking work. Its last recorded handoff names
workspace `yosoi-fingerprint-spike`, bookmark `andberg9/cas-633-linked-fingerprints`,
change `qorrqllzwvnr` / commit `22910603067a4c6d8272e390978bf8b81ee3548b`, above
article change `rkxukqkknrzn` / `5c1276c6`. These revisions were not integrated or
revalidated here. Recorded learned linking recognized 2/2 previously observed Fox
components, but literal plan transfer remained 0/4 and structural event twins were
accepted. Fresh Fox evaluation was unavailable. Preserve this work separately and
do not turn that exploratory result into a fresh-site generalization claim.

CAS-646 accounts for closeout, CAS-632 remains the research evidence ticket, and
CAS-647/648/649/652 retain future substrate scope. CAS-634/650/651 retain future
suggestion/discovery/review scope. CAS-638 and CAS-633 retain uncompleted research.
No issue is marked production-complete by this handoff.
