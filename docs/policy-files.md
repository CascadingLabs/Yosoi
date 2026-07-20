# Yosoi policy files

Yosoi resolves pipeline behavior into one immutable `ys.Policy`. Policy files are plain JSON or YAML using the `Policy` shape directly—do not wrap them in `yosoi:` or `policy:` keys.

For YAML editor completion, start files with:

```yaml
# yaml-language-server: $schema=https://cascadinglabs.com/yosoi/schemas/policy.schema.json
```

The generated schema is the authoritative field/default/constraint reference:

```bash
yosoi policy schema > policy.schema.json
```

Create starter files:

```bash
yosoi policy init --local     # .yosoi/policy.yaml
yosoi policy init --global    # ~/.config/yosoi/policy.yaml
yosoi policy init --global --local
```

## Resolution and precedence

`Policy.cascade()` merges layers from lowest to highest precedence. Only explicitly set fields override a lower layer, and nested policy models merge by field.

For scrape API execution the effective order is:

1. Yosoi defaults
2. environment-derived policy
3. contract policy
4. the explicit `policy=` value
5. direct compatibility kwargs/CLI flags

CLI policy loading composes environment, discovered global/project files, and repeated `--policy` layers in that order; later explicit layers win. A command's direct flags are applied last.

Changing model provider/name replaces the model policy wholesale so credentials from one provider cannot cross into another.

Policy values are frozen after resolution. `policy.policy_hash` is a stable content hash suitable for provenance; resolved secret values are excluded and redacted.

## Top-level policy tree

| Key | Default | Purpose |
| --- | --- | --- |
| `atom_reads` | `false` | Allow selector field-atom replay after a legacy cache miss |
| `trust_tier` | `strict` | `strict` serves verified/manual/LLM sources; `yellow` also permits quarantined fingerprint proposals |
| `model` | unset | Model/provider, generation limits, and credential reference |
| `scrape` | unset/defaults | One-scrape cache, verification, fetcher, selector, and concurrency settings |
| `search` | unset/defaults | Search provider/backend/region/safety/result bounds |
| `discovery` | unset/defaults | Selector discovery mode, concurrency, lessons, and replay threshold |
| `telemetry` | unset | Langfuse secret references and host |
| `output` | unset/defaults | Formats, terminal output, debug HTML, flat files, and logs |
| `download` | unset/default-deny | Download permission, type allowlist, location, and size/retention limits |
| `page` | unset/defaults | Acquisition tier, timeout/retry, redirects, cleaning, Chrome endpoints/profile |
| `crawl` | unset | Crawl target, budget, scheduler, safety, and escalation policy |
| `fingerprint` | unset/off | Off-path page-fingerprint signal gathering |
| `extractor` | unset/off | Deterministic extractor strategy reference writes and generalized reads |
| `recipe` | unset/defaults | Local/remote recipe trust allowlists |

## Model and credentials

```yaml
model:
  provider: groq
  model_name: llama-3.3-70b-versatile
  temperature: 0.01
  max_tokens: 4096
  credential_ref:
    source: env
    name: GROQ_API_KEY
```

Raw credentials should not appear in policy files. `SecretRef` values resolve only at execution time and resolved specs redact them from `repr`, JSON, and model dumps.

A deterministic extractor-only or cache-only execution can run without a model. If execution reaches selector/action discovery without a model, Yosoi fails closed at that boundary.

Legacy environment support includes `YOSOI_MODEL` plus provider-specific API-key variables.

## Scrape, discovery, and page acquisition

```yaml
scrape:
  force: false
  skip_verification: false
  fetcher_type: auto
  selector_level: visual
  max_concurrency: 4
  cross_origin_dom: false

discovery:
  mode: auto              # auto | static | mcp
  max_concurrent: 5
  lesson_cache: true
  replay_verify_threshold: 1.0
  static_mode_warning: true

page:
  fetcher_type: auto
  timeout_seconds: 30
  max_fetch_retries: 1
  allow_redirects: true
  clean_html: true
  cleaner_profile: discovery
  chrome_ws_urls: []
```

`cross_origin_dom` weakens Chrome site isolation for the whole browser session and is off by default. Enable it only for a known cross-origin frame requirement.

Environment equivalents include `YOSOI_FORCE`, `YOSOI_FETCHER_TYPE`, `YOSOI_SELECTOR_LEVEL`, `YOSOI_CROSS_ORIGIN_DOM`, and `YOSOI_DISCOVERY_MODE`.

## Search

```yaml
search:
  provider: ddgs
  backend: google,bing,brave
  region: us-en
  safesearch: moderate
  max_results: 10
  page: 1
  timelimit: null
```

Direct CLI flags such as `--limit` or `--backend` override durable search policy for one run.

Environment equivalents are `YOSOI_SEARCH_BACKEND`, `YOSOI_SEARCH_REGION`, `YOSOI_SEARCH_SAFESEARCH`, `YOSOI_SEARCH_MAX_RESULTS`, `YOSOI_SEARCH_PAGE`, and `YOSOI_SEARCH_TIMELIMIT`.

## Output and telemetry

```yaml
output:
  formats: [jsonl]
  quiet: true
  json_output: false
  plain_output: false
  debug_html: false
  debug_html_dir: .yosoi/debug
  flat_files: false
  logs: true

telemetry:
  langfuse_public_key_ref:
    source: env
    name: LANGFUSE_PUBLIC_KEY
  langfuse_secret_key_ref:
    source: env
    name: LANGFUSE_SECRET_KEY
  langfuse_host: https://cloud.langfuse.com
```

`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`/`LANGFUSE_HOST` are also read by the environment layer.

## Downloads

Downloads are default-deny. Settings other than `keep` are invalid unless `allow: true` is explicit.

```yaml
download:
  allow: true
  allowed_types: [pdf, csv]
  directory: .yosoi/downloads
  max_bytes: 25000000
  keep: true
```

Field-level `ys.File()` restrictions still apply; run policy does not weaken a narrower field allowlist.

## Fingerprints, atoms, and trust

```yaml
atom_reads: false
trust_tier: strict

fingerprint:
  signal_lane: true
  backpressure: defer      # defer | drop
  max_queue: 256
```

`FingerprintPolicy` controls gathering page health signals only. It does not authorize reuse. `atom_reads` separately enables selector-atom lookup, and `trust_tier` decides whether a candidate source may serve:

- `strict` (default): verified, manual, and LLM sources only.
- `yellow`: additionally permits the quarantined `fingerprint` source.
- Unknown sources are rejected under both tiers.

The rule is: **the fingerprint proposes; trust policy decides**.

## Deterministic extractor references

Local `ys.Extractor()` declarations run regardless of this policy. The extractor policy controls only content-free strategy reference I/O:

```yaml
extractor:
  reference_writes: true
  generalized_reads: false
  allowed_references: []
  allow_opaque: false
```

- `reference_writes`: persist validated portable strategies; extracted values are never stored.
- `generalized_reads`: let an otherwise unresolved extractor field consider an exact stored strategy.
- `allowed_references`: exact `module:qualname` callable allowlist; required for generalized reads so store data alone cannot authorize code loading.
- `allow_opaque`: permit generalized reuse of strategies that read only raw HTML or emit no structured evidence.

The boolean controls default to `false`, the allowlist defaults empty, and the entire block is absent by default. Generalized serving requires `generalized_reads: true`, `trust_tier: yellow`, and an exact allowed callable reference. Route/root/page/row/output/evidence checks and current-value validation still apply. Conflicts and stale or degenerate references abstain.

Prefer observation before serving:

```yaml
# Observe validated local strategies without allowing reads.
trust_tier: strict
extractor:
  reference_writes: true
  generalized_reads: false
```

Then enable quarantined reads only in an explicitly reviewed environment:

```yaml
trust_tier: yellow
extractor:
  reference_writes: false
  generalized_reads: true
  allowed_references:
    - myapp.extractors:company_links
  allow_opaque: false
```

See [`extractors.md`](extractors.md) and [`fingerprinting-stack.md`](fingerprinting-stack.md).

## Recipes

Local recipes are allowed by default. Remote recipes are deny-by-default unless exact hosts or GitHub owners are allowed. Recipe IDs and contract fingerprints become additional mandatory allowlists when present.

```yaml
recipe:
  allow_local: true
  allowed_github_owners:
    - owner
  allowed_hosts:
    - raw.githubusercontent.com
  allowed_recipe_ids:
    - v1:sha256:...
  allowed_contract_fingerprints:
    - contract:v1:sha256:...
```

See [`recipes.md`](recipes.md) for remote pinning and trust behavior.

## Crawl

Use a preset in Python for normal cases:

```python
policy = ys.Policy.for_crawl('crawl.conservative')
checked = policy.check_crawl(seeds=('https://example.com/',))
```

Available presets include `crawl.local_single`, `crawl.conservative`, and `crawl.seed_hunt`. Crawl policy is composed from:

- `mode`
- `budget`
- `scheduler`
- `safety`
- `escalation`
- `target_contracts`
- `scrape_contracts`
- `scrape_url_limit_per_contract`
- `fetcher_type`

Use `yosoi policy schema` for every nested bound and enum. `check_crawl()` derives runtime configuration and warns about idle workers, missing host scope, undersized budgets, and impolite same-host concurrency.

## Validation and troubleshooting

```bash
# Validate JSON/YAML.
yosoi policy validate .yosoi/policy.yaml

# Print the normalized policy.
yosoi policy inspect .yosoi/policy.yaml

# Inspect the complete machine-readable shape.
yosoi policy schema > policy.schema.json
```

Common fail-closed errors:

- Unknown top-level key: remove namespace wrappers or fix the spelling.
- Invalid nested field: compare with the generated schema.
- Model required: execution reached discovery without model credentials.
- Fingerprint reuse denied: enable `generalized_reads` and explicitly select yellow trust only after review.
- Pure extraction/replay store error: pass an explicit `FingerprintStore` when extractor reference I/O is enabled.
