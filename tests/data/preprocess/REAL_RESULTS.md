# CAS-18 preprocessor results on real public pages

Auto-updated by the long-tail expansion ralph loop. Each row is one
fetched snapshot; the ratio column is `tokens_out / tokens_in` measured
by `scripts/bench_preprocess.py` (chars/4 token proxy). Lower is better;
the spike's success bar is **median < 0.7**, the long-tail bar is **<
0.6 across 12+ snapshots**.

| Snapshot | Raw KB | Out KB | Ratio | Notable transform | Bytes left on the table |
| --- | ---: | ---: | ---: | --- | --- |
| nbc_news_front | 1087 | 256 | 0.236 | hydration JSON cap + `cap_oversized_attrs` shrunk inline data attrs | server-rendered ad markup; could trim further with tier-3 |
| substack_explore | 75 | 19 | 0.258 | tier-2 hydration JSON cap on `__NEXT_DATA__` | small page, mostly Next.js framework |
| theatlantic_front | 355 | 147 | 0.416 | drop_link_and_meta_noise (lots of og:* / twitter:*) | image grid metadata |
| reddit_front | 279 | 120 | 0.432 | `cap_oversized_attrs` on the 140 KB `data-cachedhtml` attribute | server-rendered post listings |
| yahoo_finance_aapl | 2637 | 1216 | 0.461 | hydration JSON cap (massive React hydration) | dense React component tree |
| arstechnica_front | 333 | 156 | 0.470 | strip_layout_attrs (srcset/sizes), strip_framework_attrs | article cards bulk |
| espn_front | 251 | 124 | 0.494 | drop_link_and_meta_noise | scoreboard hydration |
| cnn_homepage | 4636 | 2372 | 0.512 | tier-1 baseline + cap_oversized_attrs | massive page, much retained |
| github_gist | 159 | 90 | 0.571 | drop_scripts + drop_link_and_meta_noise | listing markup |
| github_pulls | 341 | 201 | 0.590 | tier-1 + hydration JSON cap | React state |
| arxiv_abstract | 47 | 28 | 0.595 | drop_link_and_meta_noise | small academic page |
| zillow_homepage | 429 | 271 | 0.631 | hydration JSON cap + cap_oversized_attrs | large image grid |
| bbc_news_homepage | 321 | 206 | 0.641 | strip_layout_attrs (srcset-heavy) | article cards |
| whitehouse_homepage | 258 | 187 | 0.725 | drop_link_and_meta_noise | hero image WordPress markup |
| stackoverflow_question | 762 | 575 | 0.755 | hoist_jsonld + drop_link_and_meta_noise | long Q+A code blocks (kept) |
| mdn_array | 235 | 179 | 0.763 | drop_link_and_meta_noise | dense reference content |
| go_dev_pkg | 464 | 408 | 0.879 | drop_link_and_meta_noise | reference docs, mostly content |
| wikipedia_python | 600 | 544 | 0.906 | tier-1 baseline | already lean; long `title=""` tooltip text remains |
| hackernews_front | 34 | 31 | 0.924 | strip_layout_attrs + strip_framework_attrs | already minimal table-based markup |
| rust_lang_docs | 51 | 48 | 0.926 | tier-1 baseline | already minimal generated docs |

**Aggregate (n=20):** median 0.5925, mean 0.601.

## Spike success conditions

- **Token reduction** — median below 0.7 ✅ (0.5925 with 20 snapshots, comfortably under).
- **No regression** — 1700+ unit/integration tests stay green; full `uv run poe ci-check` passes.
- **Selectors hold** — `tests/integration/test_preprocess_real_pages.py` validates content-anchor preservation across all 20 snapshots.

## Stretch — anchor hashes

Synthetic re-scrape harness (`tests/unit/core/cleaning/preprocess/test_anchor_hash.py::test_synthetic_rescrape_hits_50pct_structure_stable_path`) hits 93% structure-stable rate (target ≥ 50%). Cache-key wiring is the next ticket's surface.

## What's left for tier-3 / future work

Three pages still sit above 0.85 and gate further median improvement:

- **wikipedia_python** — 121 KB of `title="..."` tooltips and 97 KB of class strings. Wikipedia's `title` text is paragraph-length explanations; capping it at ~80 chars or dropping outright would cut another ~20%, but the LLM occasionally uses `[title]` for entity grounding. Out-of-scope tier-3 territory.
- **rust_lang_docs / hackernews_front** — already minimal; baseline floor.
- **go_dev_pkg** — content-heavy reference docs. Reduction is bounded by how much real content the page carries.
