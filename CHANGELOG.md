## 0.0.3a24 (2026-07-20)

### Fix

- **deps**: require VoidCrawl 0.4 or newer and lock 0.4.0.

### Test

- **stubs**: reuse the warmed mypy cache across snippet checks to prevent `ci-check` from appearing stalled.

## 0.0.3a23 (2026-07-20)

### Feat

- **CAS-235**: add async per-row extractor fields, fluent `ys.css()`/`ys.xpath()` plans, field-bound and multi-field extraction decorators, pure pre-fetched extraction, content-free fingerprints, and default-deny strategy reuse.
- **policy**: add `ExtractorPolicy` and allow deterministic/cache-only runs to defer model resolution until discovery is actually required.

### Docs

- Document deterministic extractors, fingerprint privacy/generalization, recipe portability, and the complete policy tree.

## 0.0.3a22 (2026-07-09)

### Feat

- **fetch**: add configurable bounded concurrent batches for multi-URL acquisition via `--concurrency`.
- **search**: add bounded concurrent batches for repeated or file-backed queries.
- **agents**: surface fetch batch concurrency in the Pi dashboard and packaged fetch workflow guidance.

### Docs

- Add a fetch guide covering bounded multi-URL acquisition, output semantics, and validation commands.

## 0.0.3a21 (2026-07-02)

### Fix

- **fetch**: make `yosoi fetch` normalize browser-style schemeless URLs before acquisition.
- **fetch**: keep `auto` on the simple HTTP tier for static pages with bot-vendor citations instead of escalating to Chrome.
- **fetch**: use a lightweight browser path for fetch-only rendered fallback, skipping scrape-grade DOM loading unless AX or bundle evidence is requested.
- **cli**: return machine-readable JSON errors for fetch request validation failures.

### Test

- Add live fetch benchmark harness at `scripts/bench_fetch_online.py` for release smoke checks.

## 0.0.2a19 (2026-06-04)

### Fix

- **ci**: install --all-extras in publish workflow

## 0.0.2a18 (2026-06-04)

### Feat

- **CAS-94**: de-hardcode coercion, descriptions, selectors + selecto… (#90)
- **CAS-105**: ys.File() — downloadable files as a contract field (#86)
- **CAS-79**: opinionated discovery foundation — auto static→MCP escalation, AX perception, typed ys.js(), A3Node replay (#83)

### Fix

- **licenses**: plug GPL leak in pip-licenses allow-only + add bundled-binary copyleft scan (#89)

## 0.0.1a17 (2026-05-24)

### Feat

- improve langfuse traces for OpenCode and Claude Code
- add SDK-backed model integrations
- **pipeline**: extract from raw HTML, add A3Node DOM stability storage
- made the JS DOM rendering more like a behavior tree
- made the DOM stablizer more modular
- added a DOM explorer finite state machine
- added a DOM explorer finite state machine
- **fetcher**: migrate browser fetchers from zendriver to voidcrawl
- JS fetcher waterfall with domain strategy caching and NA sentinel for absent fields
- added browser worker pool and WIP Docker building

### Fix

- **tests**: mock _verify_field instead of verify for cached path test
- **cleaner,fetcher,orchestrator,tests**: restore list truncation, fix js-shell detection, fix NA sentinel storage, update test mocks for load_snapshots
- **models,tests**: restore related_content field, fix _fetch_and_clean_for_cache tuple unpack in tests
- **fetcher,storage**: resolve mypy and ruff errors in branch files
- extract CSS pseudo-element selector values
- satisfy mypy for SDK integrations
- thread force param through _discover_selectors_impl, handle author·date in Datetime coercion
- rename fetcher 'js' → 'waterfall', fix --force flag, and improve bot gate detection
- shared fetcher with Chrome pre-warm resolves businesswire stub page loop

### Refactor

- move some utils

## 0.0.1a16 (2026-03-29)

### Feat

- added pip licenses checks to CI!

## 0.0.1a15 (2026-03-28)

## 0.0.1a13 (2026-03-28)

## 0.0.1a12 (2026-03-28)

## 0.0.1a11 (2026-03-15)

## 0.0.1a10 (2026-03-15)

## 0.0.1a9 (2026-02-20)

### Feat

- add per-URL and total elapsed time to CLI output with rich Live progress for concurrent mode
- **Contracts**: Added Dynamic Contracts with examples
- **models,-pipeline**: updated error logic handling w/ new model for failure states and reasoing
- **verifier/validator**: changed how validation and verification works. new verifier for dynamic pydantic verififcation of HTML soup

### Fix

- Ensure spaces between adjacent inline elements during body text extraction and add unit tests for text concatenation.
- **cli,-deubg**: changed gemini model, changed debug dir name

### Refactor

- mark `BaseType.__init_subclass__` as a classmethod.
- **yosoi/-dir**: better file structure for scaling better and 0.1
- **model-selectors**: chanded NA empty selector field to just be None (<null>) type. This is better for data pipelinees
- **prompts**: moved prompts to seperate dir

## 0.0.1a18 (2026-06-04)

### BREAKING CHANGE

- **Contracts**: `ys.Field(hint=...)` removed — use `description=` as the single
  per-field knob for LLM discovery guidance. Type checkers now flag `hint=`.
- **Contracts**: custom semantic types must use the `@register_coercion`
  decorator; the `YosoiType` base class / subclass-coercer path was removed.
- **Cache**: dropping `hint` from the field signature changes every contract
  signature, so on first run after upgrade the lesson and JS-script caches (keyed
  by contract signature) miss once and re-discover (one-time LLM/network cost).
  Per-domain selector snapshots are unaffected. Old `.yosoi/` lesson and
  js_script files are orphaned and safe to delete.

## 0.0.1a17 (2026-03-29)

## 0.0.1a14 (2026-03-28)

## 0.0.1a11 (2026-03-15)

## 0.0.1a10 (2026-03-15)

## 0.0.1a9 (2026-02-20)

### Feat

- add per-URL and total elapsed time to CLI output with rich Live progress for concurrent mode
- **Contracts**: Added Dynamic Contracts with examples
- **models,-pipeline**: updated error logic handling w/ new model for failure states and reasoing
- **verifier/validator**: changed how validation and verification works. new verifier for dynamic pydantic verififcation of HTML soup

### Fix

- Ensure spaces between adjacent inline elements during body text extraction and add unit tests for text concatenation.
- **cli,-deubg**: changed gemini model, changed debug dir name

### Refactor

- mark `BaseType.__init_subclass__` as a classmethod.
- **yosoi/-dir**: better file structure for scaling better and 0.1
- **model-selectors**: chanded NA empty selector field to just be None (<null>) type. This is better for data pipelinees
- **prompts**: moved prompts to seperate dir

## 0.0.1a8 (2026-02-20)

## 0.0.1a7 (2026-02-20)

## 0.0.1a5 (2026-02-14)

### Feat

- Added mutliple ways to get an output
- Added mutliple ways to get an output
- made separate cleaner and extractor in the pipeline
- Implement snapshot recording, add integration tests, and introduce debug HTML directory.
- reduce HTML through main extraction + compression and show all 5 fields in validation output
- **create-dot-files-for-yosoi**: added a new utils directory for yosoi dot directory and insurance. added unit tests for new files.py utils file
- made the bot detection better and added back models.py
- made llm more modular
- add LLM tracking and fix bot detection errors
- **requirements.txt,-pre-commit-config,-main-agent-loop**: removed requirements.txt and its precommit hooks, added better error handling around groq api key, attempted to add logfire instruments to agents
- add retry logic for selector discovery and logfire observability
- implement selector fallback system with auto-validation
- add Pydantic models for structured AI output

### Fix

- made it so you don't need to add http:// or https:// to the URL
- Output in discovery not recognizing ScrapingConfig
- Selectors only output as JSON
- added pydocstyle rules to pyproject
- resolve mypy type errors and add CLI aliases
- **files-utils,-tracker,-updated-tests**: fixed an issue where the .yosoi dir wouldn't reliable be put into the project root, added llm_tracking.json to the dot directory
- improve content extraction for Google Workspace blogs and other platforms
- correct AI provider selection logic in USE_GROQ flag
- clean up selector discovery retry logic
- Got rid of duplicates

### Refactor

- **OpenAIChatModel**: removed deprecated OpenAIModel to OpenAIChatModel
- made pipeline, fetcher, validator easier to read
- Migrate selector summary display to use storage interface instead of direct file system access.
- **src-dir**: refactor: moved yosoi to its own dir, src dir not needed
- migrate to Pydantic AI with multi-provider support and retry logic
- streamline dependencies and simplify LLM integration

### Perf

- **pycache**: removed pycache from saved files
