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
