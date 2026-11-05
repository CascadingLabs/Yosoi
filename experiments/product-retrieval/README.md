# Product fingerprint retrieval permutation matrix

**Deferred research checkpoint:** see [HANDOFF.md](HANDOFF.md) for the final
findings, evidence locations, ticket dispositions and validation limitations.
Andrew stopped further experiments/builds and kept this separate draft spike;
the broad research objective is paused, not achieved.

Experimental continuation of PR #178, isolated at `5635c7f4`. This is research
code, not the future `ys.fingerprint` SDK implementation. The objective is to
learn which representations, retrieval methods and combinations work under which
conditions, with accuracy/recall, latency, cost, ownership and failure evidence.

## Initial executable matrix

- Six immutable QScrape product DOM captures, validated by Archive identity,
  exact byte length and SHA-256. Original captures are never rewritten.
- Ten cases per capture: original, class rename, label paraphrase, field reorder,
  missing required field, recommendation decoys, multiple price roles, alternate
  layout, repeated/nested products and changed values. Each mutation starts from
  the original, not from another mutation.
- Full mutated wire DOMs, mutation provenance, target values and coordinates.
- Generic candidate enumeration over element text and attribute values. It reads
  no target annotations or old locators. Annotation is a separate fixture-only
  operation. Scorers receive candidates, Contract intent and labeled seed evidence.
- One-reference groups for lamp and mug, plus the two-reference group.
- Value-only, contextual text, and structural/contextual text representations.
- Exact weighted structural Jaccard; hierarchical category comparison; local
  motifs; tag-path edit similarity; token overlap; BM25; word and character
  TF-IDF cosine; 64/128-bit lexical and structural SimHash; semantic query and
  reference comparisons using two actual local CPU embedding encoders.
- Rank fusion, top-five support union and a structural-anchor hybrid. One
  representative per feature family avoids voting repeatedly with aliases or
  multiple correlated sketches. Individual sketch methods remain separate rows.
- Global ranking versus field ranking constrained by each method's predicted
  root. Root predictions themselves are evaluated globally. A missing root
  prediction does not silently fall back to an oracle root or global search.

Structural weights and hybrid settings are fixed development choices, not learned
confidence. The hierarchical method compares path/motif/tag/attribute categories;
it is not an implementation of arbitrary recursive Contract alignment.

## Evaluation contract

Top-1 correctness, Recall@1/3/5 and MRR use annotated candidate identities.
Equivalent descendant nodes with identical field text are accepted only within
the annotated field subtree; canonical target-node metrics are also retained.
Owner correctness, missing-field false positives, ties, abstentions, complete
root-plus-six-field records and returned context bytes are reported separately.

This initial corpus enumerates the annotated targets by construction. Its
candidate-universe coverage is therefore an integrity check, not evidence of a
learned candidate generator. Ranking recall is meaningful; proposal recall
requires a separately budgeted proposal stage and independent target annotations.

Original seed rows are excluded from transfer summaries. Mutations of seed pages
remain development evidence, and split-specific tables expose them separately.
The four other source products are previously inspected controlled examples, not
fresh validation. Synthetic alternate layouts are not real cross-site evidence.

Per-call timings measure in-memory candidate scoring. Corpus preparation,
embedding setup/download, tokenization, inference and provider usage are separate
ledger entries. Unchanged scoring results are cached by exact inputs and scorer
code identity; cache reuse is explicit. Hybrid time is an estimate of member
medians plus measured fusion, not a measured end-to-end median. Local CPU
inference has zero API charges; hardware/electricity/operator costs are unknown.
P95/P99 describe this local sample only. Risk/coverage curves are descriptive
development sweeps, not calibrated or held-out acceptance policies.

No discovery model is run in the initial matrix, so Surface steps and model repair
cost remain unmeasured. They must not be inferred from candidate recall.

## Reproduction

Use the existing synchronized Yosoi project environment for stdlib/native SDK work.
The examples below assume the workspace root is the current directory and point
UV at the existing project environment without replacing its `.venv`:

```bash
uv run --project ../Yosoi --no-sync python experiments/product-retrieval/run_matrix.py \
  freeze --output .generated/product-retrieval-minilm-v1

uv run --project ../Yosoi --no-sync python experiments/product-retrieval/run_matrix.py \
  run --output .generated/product-retrieval-minilm-v1 \
  --semantic .generated/product-retrieval-input/minilm.json

PYTHONPATH=experiments/product-retrieval:experiments/product-retrieval/extensions \
  uv run --project ../Yosoi --no-sync --with html5lib==1.1 --with idna==3.10 \
  --with zss==1.2.0 python -m pytest experiments/product-retrieval -q
```

Freeze refuses an existing destination and binds corpus and implementation hashes.
Model artifacts must cover every exact query/representation input with finite,
nonzero, consistent-dimensional vectors; an unavailable encoder is not replaced
with lexical similarity.

Embedding inference uses FastEmbed/ONNX with one CPU thread and a compatible
UV-managed Python 3.12 tooling environment because the project's Python 3.14t
environment does not have compatible embedding dependencies. It leaves the
project `.venv` intact, uses the global UV/model cache and records truncation.

```bash
ORT_INTRA_OP_NUM_THREADS=1 ORT_INTER_OP_NUM_THREADS=1 \
  uv run --no-project --python 3.12 --with fastembed==0.9.1 python ...
```

`semantic.embed_texts` is the reusable adapter. Its inputs are the unique exact
strings produced by `methods.representation_text` plus the field descriptions in
`run_matrix.FIELDS`. Save each encoder's returned vectors, metadata and ledger as
a separate JSON artifact. Retain the original text set and model weight identity.

`archive_run.py bundle` stores result files in ordinary SDK Archive JSON Documents;
`restore` verifies each payload and restores files to an empty directory. This
restoration is distinct from recomputing matching. Offline matching replay must
use restored corpus/vectors and compare actual rankings, not just a saved report.

## Broader research matrix — objective remains active

The first matrix is a starting measurement, not completion of the broad goal.
The current measured inventory is [measured-matrix.json](measured-matrix.json),
with interpretation and cohort-specific results in
[results-initial.md](results-initial.md). Local private outputs include a
69,144-row consolidated table at
`.generated/product-retrieval-consolidated-v3/results-matrix.csv`. Those rows
are overlapping metric slices, not independent examples.

Track extensions explicitly rather than treating untested ideas as losers:

| Dimension | Initial coverage | Still to exercise |
| --- | --- | --- |
| Structure | weighted/local/hierarchical Jaccard; path edit; bounded ordered fragments and exact Zhang–Shasha tree distance | semantic child correspondence; larger complete trees |
| Text | token/word/character/query/reference variants | sparse learned retrieval; multilingual paraphrases |
| Semantics | two local encoders, query prefixes, two actual cross-encoder rerankers | learned HTML encoders; broader multilingual evidence |
| Sketches | lexical/structural SimHash; consistent weighted MinHash 64/128 | sketch size/threshold tradeoffs on larger indexes |
| Hybrid | channel-subset variants; projection ablation; value-form and joint-assignment micro experiment | calibrated routing and acceptance on independent pages |
| Ownership | predicted root; repeated-product decoys; bounded flat joint assignment | arbitrary nested optional/repeated Contracts |
| Evidence | rendered DOM; source HTML; typed JSON-LD/microdata; layout/font ranking at two viewports | AX, learned visual/HTML encoders and cross-modal consistency |
| Corpus | six sources plus controlled variants; 12 fresh source pages across three templates; disjoint same-site reference comparison | more independent sites/templates; temporal drift; mutation compositions |
| Resource bounds | depth/width/attribute scaling; explicit tree and sketch limits | larger index/search scaling; compressed evidence budgets |
| Downstream | candidate rankings and context bytes | fixed-model Surface discovery steps, review/repair cost and latency |

Prioritize extensions from observed failures. Keep page/template/site/vertical
splits distinct and prevent source-derived mutations from leaking across a claimed
fresh split. Hold evaluation answers out of all retrieval and model inputs.

The experiment tree separates the frozen initial engine from later adapters:

```text
product-retrieval/
  corpus.py, methods.py, semantic.py    # Initial representations and scorers
  run_matrix.py, reporting.py          # Initial frozen campaign and summaries
  archive_run.py                      # Native Archive artifact transport
  extensions/
    campaign.py, run_wave.py           # Expanded immutable, checkpointed runs
    advanced_methods.py, tree_edit.py  # Sketches and bounded tree comparisons
    rerank*.py, projection*.py         # Pair reranking and source projection
    contract_validation.py            # Native contract plus source binding
    structured_product.py             # Typed metadata evidence, separate gold
    layout_capture.py                 # Current live DOM/geometry/PNG sidecars
    layout_retrieval.py               # Matched layout/text/DOM viewport matrix
    reference_count_wave.py           # One/two-reference matched source targets
    scopes.py                         # URL eligibility, independent of ranking
    joint_assignment.py, value_shape.py
    aggregate_wave.py, consolidate.py  # Count-aware tables with source identity
    complementarity.py, tie_audit.py   # Proposal budgets and exact tie sensitivity
    archive_campaign.py               # One-shard expanded Archive/replay proof
    test_*.py                         # Focused checks, no model downloads
```

This is a research layout. It does not define the future public SDK module tree.
Frozen runs retain the producer source used for each measurement; later cleanup
does not retroactively change that identity. Baseline runs have complete exact
Archive replays. Expanded Archive/replay coverage is certified per shard.

## Native SDK environment identity

The shared synchronized environment currently imports Yosoi 0.4.0rc1 from the editable `yosoi-surface-evidence` checkout. Native parser/Contract checks apply to that installed SDK, not a fresh build of #178 or #170. Record actual imported module paths and hashes with validation evidence. The scoring methods and retained-source truth checks are experiment code; no production SDK compatibility or build claim follows from these native checks. Do not change the shared environment to conceal this distinction.
