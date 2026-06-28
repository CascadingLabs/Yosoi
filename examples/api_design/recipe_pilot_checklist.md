# Yosoi flat recipe pilot checklist

Purpose: quick local validation for the flat JSON recipe MVP without reading the code.

## 0. What this pilot covers

A recipe is a portable JSON artifact containing:

- canonical contract JSON;
- selector snapshots keyed by domain;
- optional A3Node/action data;
- optional validation evidence;
- metadata and `recipe_id` integrity hash.

The API mirrors the CLI:

| CLI | Python |
| --- | --- |
| `yosoi recipe mint` | `ys.recipe.mint(...)` |
| `yosoi recipe check` | `ys.recipe.check(...)` |
| `yosoi recipe inspect` | `ys.recipe.load(...)` + properties |
| `yosoi recipe install` | `ys.recipe.install(...)` |
| `yosoi recipe publish` | `ys.recipe.publish(...)` |
| `yosoi recipe gist` | `ys.recipe.gist(...)` |

## 1. Local smoke test

```bash
bash examples/api_design/recipe_cli_demo.sh
```

Expected:

- prints `recipe.mint` JSON with `recipe_id: sha256:...`;
- `recipe inspect` shows `contract: Product`, `domains: example.com`, `a3nodes: 1`;
- `recipe check --json` returns status `ok`;
- `recipe install --json` writes `<cache>/<sha>.json`.

## 2. Scripted API smoke test

```bash
uv run python examples/api_design/recipe_api.py
```

Expected:

- mints the same deterministic recipe id each run;
- prints a local installed cache path;
- prints policy-gated remote install shape;
- prints piecewise consumption:
  - `contract=Product`
  - selector fields
  - A3Node count
  - fixture URLs

## 3. Manual CLI commands

Create a recipe from existing JSON files:

```bash
uv run yosoi recipe mint \
  --contract /path/to/contract.json \
  --selectors /path/to/selectors.json \
  --a3nodes /path/to/a3nodes.json \
  --validation /path/to/validation.json \
  --name example.com/products \
  --domain example.com \
  --url-pattern 'https://example.com/products/*' \
  --out /tmp/product.recipe.json \
  --json
```

Verify and inspect:

```bash
uv run yosoi recipe check /tmp/product.recipe.json --json
uv run yosoi recipe inspect /tmp/product.recipe.json
```

Install into the project-local cache:

```bash
uv run yosoi recipe install /tmp/product.recipe.json --json
```

Install a remote flat JSON recipe:

```bash
uv run yosoi recipe install \
  'gh:owner/yosoi-recipes/recipes/example.com/products/v1/recipe.json@main' \
  --recipe-id 'sha256:EXPECTED...'
```

GitHub blob URLs are also accepted and rewritten to raw URLs:

```bash
uv run yosoi recipe install \
  'https://github.com/owner/yosoi-recipes/blob/main/recipes/example.com/products/v1/recipe.json' \
  --recipe-id 'sha256:EXPECTED...'
```

## 4. Quick secret/unlisted Gist publish

Default is GitHub secret/unlisted, not access-controlled private: anyone with the URL can read it. Requires `GITHUB_TOKEN` or `GH_TOKEN` with gist permission. Use a private repo or another access-controlled store for sensitive recipes.

```bash
GITHUB_TOKEN=... uv run yosoi recipe gist /tmp/product.recipe.json \
  --filename product.recipe.json \
  --description 'Yosoi product recipe' \
  --json
```

Make it public only when intentional:

```bash
GITHUB_TOKEN=... uv run yosoi recipe gist /tmp/product.recipe.json --public
```

Python equivalent:

```python
import yosoi as ys

gist = ys.recipe.gist(
    './product.recipe.json',
    filename='product.recipe.json',
    description='Yosoi product recipe',
)
print(gist.raw_url)   # direct JSON URL accepted by ys.recipe.load/install
print(gist.html_url)  # browser page

# Consume a Gist raw URL with a pin/trust policy:
recipe = ys.recipe.install(
    gist.raw_url,
    recipe_id='sha256:EXPECTED...',
    policy=ys.Policy(recipe=ys.RecipePolicy.github('your-github-user').contracts(Product)),
)
```

## 5. Repo publish

Requires `GITHUB_TOKEN` or `GH_TOKEN` with repo contents permission.

```bash
GITHUB_TOKEN=... uv run yosoi recipe publish /tmp/product.recipe.json \
  --repo owner/yosoi-recipes \
  --path recipes/example.com/products/v1/recipe.json \
  --branch main \
  --json
```

Python equivalent:

```python
import yosoi as ys

url = ys.recipe.publish(
    './product.recipe.json',
    repo='owner/yosoi-recipes',
    path='recipes/example.com/products/v1/recipe.json',
    branch='main',
)
```

## 6. Trust-policy pilot

Remote recipe acceptance is deny-by-default unless trust is explicit.

```python
import yosoi as ys

class Product(ys.Contract):
    title: str = ys.Title(description='Product title')

policy = ys.Policy(
    recipe=ys.RecipePolicy.github('owner').contracts(Product)
)

recipe = ys.recipe.install(
    'gh:owner/yosoi-recipes/recipes/example.com/products/v1/recipe.json@main',
    policy=policy,
)
```

Tighten by exact recipe id:

```python
policy = ys.Policy(
    recipe=ys.RecipePolicy.github('owner')
    .contracts(Product)
    .recipe_ids('sha256:EXPECTED...')
)
```

Trust dimensions:

- `RecipePolicy.local_only()` — local files only;
- `RecipePolicy.github('owner-or-org')` — specific GitHub user/org, including `github.com`, `raw.githubusercontent.com`, and `gist.githubusercontent.com/<owner>/...` raw Gist URLs. It still allows local files by default; use `ys.RecipePolicy.github('owner').model_copy(update={'allow_local': False})` if you need GitHub-only;
- `RecipePolicy.hosts('recipes.example.com')` — exact host allowlist;
- `.contracts(Product)` — exact contract fingerprint;
- `.recipe_ids('sha256:...')` — exact artifact identity.

## 7. Piecewise consumption

You do not have to use a recipe all-or-nothing:

```python
recipe = ys.recipe.load('./product.recipe.json')

Contract = recipe.to_contract()
selectors = recipe.selectors_for('www.example.com')
a3nodes = recipe.a3nodes
fixture_urls = recipe.fixture_urls()
```

## 8. Stress checks to run before trusting a change

```bash
uv run ruff check \
  yosoi/recipe.py yosoi/models/recipe.py yosoi/storage/recipe_store.py \
  yosoi/policy/recipe.py yosoi/policy/core.py yosoi/cli/main.py \
  tests/unit/test_recipe_api.py tests/unit/storage/test_recipe_store.py tests/unit/cli/test_recipe_commands.py \
  examples/api_design/recipe_api.py

uv run mypy \
  yosoi/recipe.py yosoi/models/recipe.py yosoi/storage/recipe_store.py \
  yosoi/policy/recipe.py yosoi/policy/core.py yosoi/cli/main.py

uv run pytest \
  tests/unit/test_recipe_api.py \
  tests/unit/storage/test_recipe_store.py \
  tests/unit/cli/test_recipe_commands.py \
  tests/stubs/test_stub_completeness.py

bash examples/api_design/recipe_cli_demo.sh
uv run python examples/api_design/recipe_api.py
```

Current known limitations:

- Recipes can be minted, checked, installed, published, and consumed as pieces.
- Full `ys.scrape(..., recipe=...)` replay is not wired in this MVP; use the loaded contract/selectors pieces or the cache install path until replay integration lands.
- CLI recipe commands do not yet take `RecipePolicy`; for remote CLI installs use `--recipe-id sha256:...` pins. Python `ys.recipe.*(..., policy=...)` is the stricter trust path.
- Gist creation uses GitHub `POST`; if GitHub creates the gist but the response is lost, retry can create a duplicate gist. If that matters, prefer repo publish or manually verify gists after timeout.

## 9. Failure-mode checks

Tampering should fail:

```bash
cp /tmp/product.recipe.json /tmp/tampered.recipe.json
python - <<'PY'
import json
p = '/tmp/tampered.recipe.json'
d = json.load(open(p))
d['contract']['name'] = 'Tampered'
json.dump(d, open(p, 'w'))
PY
uv run yosoi recipe check /tmp/tampered.recipe.json
# expected: non-zero integrity failure
```

Publishing without a token should fail safely:

```bash
env -u GITHUB_TOKEN -u GH_TOKEN uv run yosoi recipe gist /tmp/product.recipe.json
# expected: GitHub Gist publish requires GITHUB_TOKEN or GH_TOKEN
```

Remote load without trust should fail before fetching in Python:

```python
import yosoi as ys
ys.recipe.load('gh:unknown/repo/recipe.json@main')
# expected: PermissionError, no trusted remote origin/user configured
```
