# Search diagnostic capture and replay

Ordinary Search retains content-free attempt facts, including parser reasons,
document class/bytes, capture completeness, and retention state. Query URLs and
projected document bytes are retained only after an explicit capture opt-in.

```bash
yosoi search 'history of photosynthesis' --providers bing --max-in-flight 1 \
  --diagnostic-archive .generated/search-evidence --output json
yosoi search replay .generated/search-evidence/search-REQUEST_ID.json
```

The first command contacts the provider. The replay command performs zero network
requests and restores exact Documents through the existing Archive integrity checks.
It reports original/recovery records separately, including paired representations,
and compares the original content-free decision with the current parser decision.
Exit 1 means a decision changed; exit 2 means no replay documents were retained.
HTTP blocks remain blocks, independently of their page markup. A successful HTTP
response or zero accepted rows cannot establish an actual empty result.

The bounded diagnostic manifest keeps provider statuses, attempt/capture facts,
coverage, and counts; normalized result text is written only to ordinary Search
output. If requested archival saving fails, Search still writes its complete
result output and exits unsuccessfully with an explicit diagnostic capture error.

Rust callers opt in with `search::new(query)?.bind(&policy).with_diagnostic_capture()`.
Each `ProviderResult::captures()` entry provides its Document, safe capture
environment, original/recovery URLs and observed parser result. Save with
`capture.save(&archive).await?`, serialize returned `SearchReplay` records, and
replay with `record.replay(&archive).await?`. A JSON object containing
`{"schema_version":1,"records":[...]}` is also accepted by the CLI replay command.

Python uses `await request.send(diagnostic_archive=archive)` and preserves those
same records in `provider.captures`. Call `await record.replay(archive)` or use
`search.replay_document(provider, document, provider_page_url, replay_policy)` on
an already retained Document. The corpus runner can exercise either CLI or SDK.

Capture bytes share a per-provider quota derived from Search's existing
`max_retained_content_bytes`, separate from normalized results. Original and
recovery captures share that quota. Whole documents are omitted instead of
truncated when they do not fit; attempt `capture_retention=byte_limit` records the
gap. Requests acquisition failures do not expose projected Documents, so these
retain typed acquisition diagnostics and `missing_document` retention, with no
invented replay payload. Retaining evidence does not change provider parsing.

The manifest stores only document/locator parsing policy and tuning, plus safe
environment and effective policy identity. It excludes Requests network settings,
proxy credentials, cookies, headers, and browser launch arguments. Document bodies
and URLs can still contain sensitive query/page content: review and sanitize
before sharing or committing a fixture. Captured files are local evidence, and
never enter CI automatically.

The CLI records its executable SHA-256 separately from SDK/parser versions.
`YOSOI_BUILD_SOURCE_REVISION` can embed a build-time source revision assertion.
That assertion and a version string do not prove exact-source validation: correlate
the executable hash, source revision, focused checks, and hosted CI externally.
Browser/controller facts come from Requests' existing secret-safe CaptureEnvironment;
missing identities remain absent rather than inferred from a version string.

## Small public-query corpus

`corpus.json` contains ordinary terms, intent questions, quoted/operators, Unicode,
and a deliberately sparse public phrase. This is a repair sample, not a search
quality benchmark. The report includes every authored provider/case cell, including
failures and skips. HTTP success, hit count, and lexical topic relevance are separate
fields. `useful_results_proxy` is explicitly a lexical topic proxy; human query-intent
judgment remains unverified.

```bash
# Default is offline: every cell is reported as skipped and no executable is run.
uv run --no-sync python scripts/search/run_corpus.py

# Explicit live opt-in: at most three serial provider cells; stop on challenge/429.
uv run --no-sync python scripts/search/run_corpus.py --live --interface cli \
  --binary /absolute/path/to/yosoi --providers bing --max-cells 3

# The installed native SDK must match the source under review.
uv run --no-sync python scripts/search/run_corpus.py --live --interface sdk \
  --providers bing --max-cells 3

uv run --no-sync python -m unittest discover -s scripts/search -p test_corpus.py
```

The runner records exact CLI/native-extension bytes and an optional caller source
assertion, stops serial execution on a block/rate limit, and counts remaining cells
as skipped. It does not rotate proxies, retry challenges, or fetch result URLs.

`crates/yosoi/src/internal/engine/tests/fixtures/search-diagnostics/provenance.json` labels every committed control **synthetic**, with byte
counts and SHA-256. The synthetic Bing original/recovery pair verifies the replay
mechanism and stage distinction; it is not evidence that an observed live mismatch
was correct. Provider tickets own sanitized observed failure fixtures and provenance.

`examples/search_acquisition.rs` is a lower-level public Requests probe for paired
source/rendered documents. The initial Google/Brave investigation ran its earlier
source at local revision `c81a25d2`; that historical identity is not the current
example's validation identity. The current example omits full Policy serialization.
The public Requests facade does not yet expose CaptureEnvironment directly, so this
probe records that missing integration capability explicitly. Search diagnostic
captures include the environment when Requests recorded a projected Document.
