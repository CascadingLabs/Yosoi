# Local Search HTTP evidence, 2026-10-03

Scope: local-only Brave and Bing Direct HTTP Search through Yosoi Requests. This
is feasibility and parser evidence, not provider-default certification or a
public usage grant. Google and browser execution were outside this run.

## Execution identity

- Source candidate: JJ change `zwputyst`, snapshot `2f9c0020` after the corpus;
  the Search CLI binary used for the corpus has SHA-256
  `774f7d99e2d114fc79bbf47b39f11843648221d9269f571b6650f696eeb1aad9`.
- Host: Linux 7.2.5-3-omarchy x86_64; Rust 1.98.0. No browser was used.
- CLI schema 1; Policy identity projection v4. A temporary local Policy profile
  selected Exact standard Direct HTTP Requests routes for Brave and Bing,
  rather than the still-unavailable Current defaults. Search limited each
  provider to ten retained hits, allowed two in flight, and retained a
  separate Requests capture ID, HTTP status, and source-artifact byte count.
- The `source_bytes` below are exact retained source artifact extents, not wire
  transfer totals. Elapsed time was not instrumented in this corpus.

## Offline captured-page replay

A serial, hash-checked replay used the saved CAS-502 local captures without
network access. Brave standard (302,543 bytes) yielded 20/20 validated HTTP(S)
links; Bing standard (121,222 bytes) and Bing `safari26` (610,002 bytes) each
yielded 10/10. All three had zero invalid-destination issues. The saved Brave
`safari26` 429 (73,818 bytes) classified as rate limited by its recorded status;
its body was not parsed as results. Fixture provenance and redaction details
are in `crates/yosoi/tests/fixtures/search-providers/`.

## Live bounded corpus

Each row below is one provider result from the Yosoi CLI. The informational,
time-sensitive, regional, and expected-empty-intent operations selected both
providers concurrently, with response slots in Brave then Bing Policy order.
All listed rows had HTTP 200, `Results`, complete web coverage, zero issues,
and unknown monetary charge; rich features were not collected.

| Query class | Query | Brave hits / source bytes | Bing hits / source bytes |
| --- | --- | ---: | ---: |
| Navigational | `Rust programming language official website` | 10 / 259,450 | 10 / 118,246 |
| Informational | `how to parse HTML in Rust` | 10 / 299,976 | 10 / 119,341 |
| Time-sensitive | `Rust release October 2026` | 10 / 260,402 | 10 / 118,902 |
| Regional wording | `public libraries in Boston Massachusetts` | 10 / 729,025 | 7 / 114,324 |
| Expected-empty intent | `"zzzxqv_no_result_probe_20261003_8e31a6"` | 10 / 247,934 | 10 / 115,963 |
| Expected-empty intent | `"qzjvplmwnrxtkb20261003fca9e70d462d47b1933e1a2f5c6d8b0a"` | 10 / 195,647 | 10 / 118,738 |

The two nonsense queries did **not** produce verified empty pages: both
providers returned organic rows. They cannot certify `Empty` classification.
The first live Brave run revealed that reaching the requested ten-hit cap was
incorrectly reported as partial. The parser fix was tested against captured
multirow fixtures, and the navigational Brave query was repeated successfully
with ten complete hits and no issues; only the corrected run appears in the
table.

A final local `site:example.invalid` Request saved raw pages under `/tmp` to
look for an actual no-results marker. Brave returned a 73,712-byte page with
zero result rows and structural markers matching the saved Brave 429 page; its
HTTP status was not captured by that raw-output command, so this is a
rate-state **inference**, not a measured 429. Brave probing stopped there.
Bing returned a 120,614-byte page with ten `b_algo` rows. A generic
"no results" phrase appeared only in script localization text, not as a
verified visible empty-state marker. Probing stopped after this pass; no domain
quota is inferred.

## Decision

Positive-query extraction and two-provider ordering passed locally. At this HTTP-only evidence snapshot, Brave and
Bing Current defaults remained **Unavailable** because genuine empty and
challenge-page classification, a timed corpus, and broader selector/placement
coverage are not yet certified. Unknown zero-row pages fail closed as malformed
instead of being called empty. The next pass needs exact Requests status and
completion facts for a genuine no-results page, sanitized provider-specific
empty/challenge fixtures, then a small timed corpus after the observed Brave
rate state clears. No hidden retry, alternate TLS/browser profile, or
provider fallback was used here.

## Follow-up: headless Brave candidate and off-query Bing pages

A later local default `yosoi search "history of cotton candy" --stats` run
reported Brave `rate_limited`; the pasted human output did not include the HTTP
status or retained response body. One separate, explicit headless Browser
Request in the hardened regular-Stable Chrome 154.0.8037.97 container returned
HTTP 200 and 310,144 retained source bytes. Its search box echoed the full
query and its HTML had 20 Brave result wrappers. The raw local page is
`/tmp/yosoi-brave-headless-cotton-candy.html` (SHA-256
`323543287353f92fd4dc1af114b1acc2adf34553e58e6d7eb4a950d4caab862c`).
A subsequent Brave-only Search call with an explicit headless Browser
ResponseDocument+RenderedDom profile returned five validated relevant hits,
complete web coverage, zero row issues, HTTP 200, and exit 0 in 2.475 seconds.
Both calls used image
`sha256:53b6cf8e12f5632e357711454dd1b5946077d00fa2910f7711e6327c08826c2c`,
regular Stable Chrome, required sandbox, read-only root, UID 10001, dropped
capabilities, the repository seccomp profile, and bounded resources. One
mounted-Policy attempt failed before provider I/O because the temporary file
was not readable by UID 10001; it was corrected before the Search call. The
Brave Current local-preview profile now uses this headless route at provider
version 2. This is positive candidate evidence, not certification of its
challenge, empty, repeatability, or rate behavior.

Bing showed a different failure. The user's earlier CLI run returned generic
"history" results for a cotton-candy query. We reproduced the shape with
`how to make sourdough bread`: Bing's HTTP 200 page echoed the complete query
in its search box and title, while ten `b_algo` organic rows were about the
unrelated automation product "Make". The Direct HTTP raw page is retained only
under `/tmp/yosoi-bing-sourdough-raw.html` (120,594 bytes, SHA-256
`8a9b6cdf7c7e1961d9649100582542b508ac106bd7353bed0ef7c4cce96a6154`).
A headless Browser Request also received off-query "Make" rows, so changing
Bing acquisition did not fix the page. Percent-encoded spaces produced the
same provider response. The Search adapter now rejects a multiword ASCII query
when at least three accepted Bing hits contain none of a distinctive trailing
query term in title, snippet, or destination, returning typed `query_mismatch`
instead of `Complete` off-topic results. Single-word, operator, non-ASCII, and
short-result cases remain unclassified by this conservative check; it is not
a general relevance guarantee. A sanitized synthetic control and a
hash-checked replay of the retained bad page pass; a relevant cotton-candy
Search remains accepted.

For rate-state evidence, 900 serial Bing Search calls were logged locally,
including 320 off-query responses across four of ten varied query families.
A further 2,100 explicit Direct HTTP Requests ran in bounded two-, four-,
eight-, and sixteen-in-flight batches. Every logged raw Request returned HTTP
200 with organic rows; no hard 429/challenge threshold was observed through
sequence 2,800. The stress batches stopped there to keep the workstation
responsive. This does not establish that Bing has no rate limit or define a
safe sustained request rate. Sequence facts are retained in
`/tmp/yosoi-bing-pressure.jsonl` and `/tmp/yosoi-bing-rate-pressure.jsonl`;
raw query pages, links, and opaque tokens are not committed.

The rebuilt native CLI on this workstation used Arch Chromium
152.0.7977.82-1 and the new Brave headless Preview profile version 2. For the
same cotton-candy query it still received HTTP 429 (73,801 retained source
bytes) and returned `rate_limited`, while Bing Direct HTTP returned relevant
hits. The container's regular Stable Chrome 154.0.8037.97 positive Brave
candidate therefore does not establish success for the native host runtime.
Browser executable, disposable profile, runtime environment, and rate state
differ; this evidence does not isolate which difference caused the 429. Brave
probing stopped after it. The reviewed local container remains the positive
preview path for that candidate.

For the off-query Bing page, adding `form=QBLH`, `setlang=en-US` and `cc=US`,
their combination, or `first=1&count=10` did not change the generic "Make"
organic rows. A rebuilt Bing-only CLI call on the retained query returned
`failed(query_mismatch)`, zero hits, and exit 1; a relevant cotton-candy control
still returned five hits and exit 0. The Bing parser identity is now
`bing-html-v2`. These checks establish fail-closed handling for the captured
wrong-page shape, not a way to make Bing return relevant results for every
query.

The final default-workspace review image was built from JJ change
`rsllxxuqzuvlsonwqzpxrlmwknrvywso`, source snapshot
`f867d5666a2b640534384c60d5c28590c2591d70`, filtered source SHA-256
`4556facda8232db5cd40360f25a7eb6e84f85bf3a31dc3d89c082d0332680086`,
and image ID
`sha256:464d8a4ee78e6da37599c0dd411fd69c7ba2d5ff3986770b9f45e705014118e2`.
It used the reviewed regular Stable Chrome 154.0.8037.97 package and
executable hashes, required sandbox, UID 10001, read-only root, dropped
capabilities, seccomp, and bounded resources recorded in
[the container evidence](search-ddg-container-evidence-2026-10-03.md).
One default CLI query for cotton-candy history returned ordered Brave headless
Preview v2, Bing Direct HTTP Preview v1, and DuckDuckGo headless Preview v1,
each with HTTP 200, five hits, complete web coverage, zero row issues, and
exit 0. `--stats` reported 5.254 seconds wall time and 15 hits. A separate
Bing-only sourdough negative control returned HTTP 200 but
`failed(query_mismatch)`, zero hits, parser identity `bing-html-v2`, and exit 1.
Neither bounded call certifies provider repeatability, and the native host
Brave 429 remains unresolved.

## Follow-up: Contract rows and Bing content-term recovery

The retained sourdough HTTP page already contained ten organic cards about
"Make" while echoing the complete user query. The same simple `li.b_algo`
locator extracted those cards correctly; no selector can recover sourdough
links from that source. New bounded Direct HTTP comparisons showed the original
`how to make sourdough bread` query returning "Make" cards in one run, while
`sourdough bread` returned bread recipes. `format=rss` repeated the wrong
cards, and quoting the entire query returned generic "how" results. For the
other recorded failures, `paper airplanes` and `quokka` returned topic-matched
cards; `sunflower scientific name` remained broad, so the recovery uses the
distinctive `sunflower` term and reports partial coverage.

All three provider row parsers now pass their located URL, title, and summary
fields through Yosoi Contracts for field cardinality and provenance. Bing and
Brave use pinned Contract locators; DuckDuckGo keeps its provider-owned plan
for the ad/organic placement distinction and validates its repeated rows with
the same Contract SDK. HTTP(S) destination checks, Bing wrapper decoding,
organic rank, and output budgets remain Search rules after Contract validation.

Current Bing Preview v2 can make one more Direct HTTP Request only after an
original `query_mismatch`. It removes broad ASCII query words, records both
Request and capture IDs, and shows the exact second query in CLI JSON/human
output. A recovered page must mention a distinctive term from the original
query. Its hits are explicitly partial with `query_relaxed`; an unrecovered
page still fails closed. Exact Bing routes retain a single Request. The CLI
JSON schema is now version 2.

One rebuilt native Bing-only CLI pass returned five complete sourdough hits
from the original query and five complete cotton-candy hits. Paper-airplane
history and sunflower scientific-name queries each used two HTTP-200 Requests
and returned five topical, partial hits. In particular, the paper-airplane
recovery returned folding guides rather than an answer about history. Five
other Bing phrasings that retained the history intent returned generic results
about "Paper," "Origins," or "Were," so this is not a full semantic recovery.
The quokka query failed once after
two HTTP-200 Requests, then returned partial hits in eleven subsequent bounded
runs; this is evidence of provider variability, not a reliability guarantee.
In a final serial corpus of five runs each for sourdough, paper airplanes,
sunflower, and quokka, all 20 returned hits: sourdough used one Request with
complete coverage each time, and the other three used two Requests with
partial coverage each time. Per-run status, first title, and Request count are
retained locally in `/tmp/yosoi-bing-contract-recovery-corpus.json`.
The 29 focused provider tests passed, the retained off-query sourdough page
replayed as `query_mismatch`, the pinned Contract attribute test passed, and
the 11 Search CLI unit tests passed. Focused Policy identity, Search SDK
contract, archive Policy round-trip, and Yosoi/CLI Clippy checks also passed.
The public `yosoi-sdk` focused tests passed after the Contract locator addition.
No broad provider certification is claimed.
