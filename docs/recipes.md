# Yosoi recipes

Yosoi recipes are portable, flat JSON artifacts for replaying a discovered scrape without asking an LLM again. A recipe bundles:

- a `ContractSpec` describing the output shape;
- verified selector snapshots keyed by domain;
- optional A3Node browser actions for cookie banners, popups, tabs, load-more flows, and other rendered-page steps;
- optional validation evidence and human metadata.

The default posture is fail-fast: a recipe either verifies and has selectors for the target domain/route, or replay fails. It does not silently fall back to heuristic scraping.

## Artifact identity

Every recipe has a deterministic id:

```text
v1:sha256:<digest>
```

The digest is computed from canonical JSON over the semantic payload. Runtime comments are not valid JSON, so minted recipes include top-level `instructions` data instead. The following are excluded from the id so review notes and provenance can evolve without changing the recipe identity:

- `recipe_id`;
- `instructions`;
- metadata `created_at`, `created_by`, and `notes`;
- volatile selector audit fields such as discovery/verification timestamps and failure counters.

Always pin remote recipes with `--recipe-id` or `recipe_id=`.

## Mint from the CLI

Mint from the local selector cache for a known URL and contract:

```bash
uv run yosoi recipe mint \
  --contract @Product \
  --from-cache https://example.com/products/sku-1 \
  --domain example.com \
  --url https://example.com/products/sku-1 \
  --url-pattern 'https://example.com/products/*' \
  --out .yosoi/recipes/ \
  --yes
```

Mint from explicit JSON inputs:

```bash
uv run yosoi recipe mint \
  --contract ./product.contract.json \
  --selectors ./selectors.json \
  --a3nodes ./a3nodes.json \
  --validation ./validation.json \
  --out ./product.recipe.json
```

`--selectors` and `--from-cache` are mutually exclusive. If `--out` is a directory, Yosoi writes `<contract>-<hash>.recipe.json` inside it.

## Compile and export contracts

Recipes carry canonical `ContractSpec` JSON. Compile a Python-authored contract before minting or publishing artifacts:

```bash
uv run yosoi recipe contract compile path/to/contracts.py:Product -o product.contract.json
uv run yosoi recipe contract compile product.contract.json --json
```

Export a recipe or `ContractSpec` JSON back to importable Python for review:

```bash
uv run yosoi recipe contract export product.recipe.json -o product_contract.py
uv run yosoi recipe contract export product.contract.json
```

Python equivalents:

```python
spec = ys.recipe.compile_contract('path/to/contracts.py:Product')
source = ys.recipe.render_contract_py(spec)
```

## Inspect, check, validate, and install

```bash
uv run yosoi recipe inspect .yosoi/recipes/product.recipe.json
uv run yosoi recipe check .yosoi/recipes/product.recipe.json --recipe-id v1:sha256:...
uv run yosoi recipe validate .yosoi/recipes/product.recipe.json \
  --url https://example.com/products/sku-1 \
  --write
uv run yosoi recipe install .yosoi/recipes/product.recipe.json
```

`recipe validate` replays the recipe against fixture URL(s), builds validation evidence, and exits non-zero unless replay returns records for every required contract field. It records `missing_fields` in the validation summary on failure.

Validation changes the recipe identity because validation evidence is part of the artifact. Use `--write` to update the input file, or `--out validated.recipe.json` to write a new validated copy.

Local installs cache the verified canonical recipe under `.yosoi/recipes/v1-sha256-....json`.

Remote sources can be HTTPS URLs or GitHub refs:

```bash
uv run yosoi recipe install \
  'gh:owner/yosoi-recipes/recipes/example.com/product.recipe.json@main' \
  --recipe-id v1:sha256:...

uv run yosoi recipe install \
  'https://raw.githubusercontent.com/owner/yosoi-recipes/main/recipes/example.com/product.recipe.json' \
  --recipe-id v1:sha256:...
```

The CLI refuses remote recipe installs and `--recipe` scrapes without a pinned `--recipe-id`.

## Run a recipe

Use an installed/local recipe with scrape:

```bash
uv run yosoi scrape https://example.com/products/sku-2 \
  --recipe .yosoi/recipes/product.recipe.json \
  --recipe-id v1:sha256:...
```

Omit the recipe source to pick from local recipes interactively:

```bash
uv run yosoi scrape https://example.com/products/sku-2 --recipe
```

Recipe replay sets `--no-llm` behavior by default. Pass `--allow-llm-with-recipe` only when you intentionally want discovery/repair after a recipe miss.

## Publish

Publish requires passed validation evidence by default. Run `yosoi recipe validate ... --write` first, or pass `--allow-unvalidated` intentionally for examples/pilots.

Publish to a GitHub repository by pull request, which is the default safer mode:

```bash
uv run yosoi recipe publish ./product.recipe.json -r owner/yosoi-recipes
```

Commit directly only when you mean to mutate the target branch:

```bash
uv run yosoi recipe publish ./product.recipe.json -r owner/yosoi-recipes --direct
```

Publish a secret/unlisted Gist:

```bash
uv run yosoi recipe publish ./product.recipe.json --gist
uv run yosoi recipe gist ./product.recipe.json
```

Secret/unlisted Gists are not private access control; anyone with the raw URL can read them. GitHub auth is resolved from `GITHUB_TOKEN`, `GH_TOKEN`, or `gh auth token`.

## Python API

```python
from datetime import datetime, timezone
import yosoi as ys


class Product(ys.Contract):
    title: str = ys.Title(description='Product title')
    price: str = ys.Price(description='Displayed price')


selectors = ys.recipe.selector_map(
    'https://example.com/products/sku-1',
    discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    title='h1.product-title',
    price='.price',
)
recipe_path = '.yosoi/recipes/product.recipe.json'

recipe = ys.recipe.mint(
    Product,
    selectors=selectors,
    out=recipe_path,
    source_urls=['https://example.com/products/sku-1'],
    url_patterns=['https://example.com/products/*'],
)

validated = await ys.recipe.validate(
    recipe_path,
    ['https://example.com/products/sku-1'],
    write=True,
)
loaded = ys.recipe.load(recipe_path, recipe_id=validated.recipe.recipe_id)
await ys.recipe.run(loaded, 'https://example.com/products/sku-2')
```

Recipes can also be consumed piecewise:

```python
RecipeContract = loaded.to_contract()
selector_map = loaded.selectors_for('www.example.com')  # falls back to example.com
actions = loaded.a3nodes
fixture_urls = loaded.fixture_urls()
```

## Trust policies

API recipe loading is local-only by default. Remote sources require an explicit trust boundary, and additional allowlists compose with AND semantics.

```python
trust = ys.recipe.Trust.github('owner').contracts(Product).recipe_ids(recipe.recipe_id)
remote = ys.recipe.load(
    'gh:owner/yosoi-recipes/recipes/example.com/product.recipe.json@main',
    recipe_id=recipe.recipe_id,
    trust=trust,
)
```

Policy files can carry the same allowlist:

```yaml
recipe:
  allow_local: true
  allowed_github_owners:
    - owner
  allowed_recipe_ids:
    - v1:sha256:...
  allowed_contract_fingerprints:
    - contract:v1:sha256:...
```

## Cache and route behavior

Recipe runs seed recipe selectors into the normal selector cache for each requested URL before scraping. Current selector loads are route-scoped by normalized path, so `/news/article/` and `/eshop/` can share a domain and contract fingerprint without mixing fields.

A recipe containing A3Node actions automatically enables experimental A3Node replay for that scrape. Scoped A3Node storage keys include domain, route shape, query-key shape, replay intent, and browser/profile fingerprint so unrelated page templates or browser identities do not overwrite each other.

## Command reference

- `yosoi recipe contract compile` — compile `path.py:Class` or contract JSON to canonical `ContractSpec` JSON.
- `yosoi recipe contract export` — render recipe/contract JSON as importable Python.
- `yosoi recipe mint` — create recipe JSON from a contract plus selectors or cache state.
- `yosoi recipe inspect` — summarize contract, fields, domains, A3Nodes, and validation status.
- `yosoi recipe check` — verify schema and deterministic identity.
- `yosoi recipe validate` — replay fixture URL(s), require all contract fields, build evidence, optionally write it back.
- `yosoi recipe install` — verify and cache local/remote recipes.
- `yosoi recipe list` — list local `.yosoi/recipes` artifacts.
- `yosoi recipe publish` — publish to GitHub repo PR/direct commit and/or Gist.
- `yosoi recipe gist` — convenience Gist publish command.
