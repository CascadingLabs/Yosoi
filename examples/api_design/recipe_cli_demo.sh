#!/usr/bin/env bash
# Flat recipe CLI demo.
#
# Run:
#   bash examples/api_design/recipe_cli_demo.sh
#
# Shows:
#   yosoi recipe mint     -> canonical recipe.json
#   yosoi recipe inspect  -> human/machine summary
#   yosoi recipe check    -> integrity verification
#   yosoi recipe install  -> local hash-keyed cache install
#
# Publish to a repo, when you have a token:
#   GITHUB_TOKEN=... uv run yosoi recipe publish "$RECIPE" \
#     --repo owner/yosoi-recipes \
#     --path recipes/example.com/products/v1/recipe.json \
#     --branch main
#
# Or make a quick secret/unlisted Gist (not access-controlled private):
#   GITHUB_TOKEN=... uv run yosoi recipe gist "$RECIPE" \
#     --filename product.recipe.json \
#     --description "Yosoi product recipe"

set -euo pipefail

WORKDIR="${1:-$(mktemp -d)}"
mkdir -p "$WORKDIR"

CONTRACT="$WORKDIR/product.contract.json"
SELECTORS="$WORKDIR/product.selectors.json"
A3NODES="$WORKDIR/product.a3nodes.json"
VALIDATION="$WORKDIR/product.validation.json"
RECIPE="$WORKDIR/product.recipe.json"
CACHE="$WORKDIR/cache"

cat > "$CONTRACT" <<'JSON'
{
  "schema_version": 1,
  "name": "Product",
  "doc": "Product detail page",
  "fields": {
    "title": {
      "yosoi_type": "title",
      "description": "Product title",
      "python_type": "str",
      "required": true
    },
    "price": {
      "yosoi_type": "price",
      "description": "Displayed product price",
      "python_type": "str",
      "required": true
    }
  }
}
JSON

cat > "$SELECTORS" <<'JSON'
{
  "url": "https://example.com/products/sku-1",
  "domain": "example.com",
  "snapshots": {
    "title": {
      "primary": "h1.product-title",
      "fallback": "h1",
      "discovered_at": "2026-01-01T00:00:00Z",
      "source": "discovered",
      "status": "active"
    },
    "price": {
      "primary": ".price",
      "fallback": "[data-price]",
      "discovered_at": "2026-01-01T00:00:00Z",
      "source": "discovered",
      "status": "active"
    }
  }
}
JSON

cat > "$A3NODES" <<'JSON'
[
  {
    "name": "accept_cookie_banner",
    "acts": [
      {"kind": "click", "selector": "button.accept"},
      {"kind": "wait_for", "selector": "body.ready"}
    ]
  }
]
JSON

cat > "$VALIDATION" <<'JSON'
{
  "fixture_urls": ["https://example.com/products/sku-1"],
  "expected_shape": {"title": "str", "price": "str"},
  "summary": {"status": "example-only", "field_count": 2}
}
JSON

uv run yosoi recipe mint \
  --contract "$CONTRACT" \
  --selectors "$SELECTORS" \
  --a3nodes "$A3NODES" \
  --validation "$VALIDATION" \
  --name "example.com/products" \
  --domain example.com \
  --url-pattern 'https://example.com/products/*' \
  --out "$RECIPE" \
  --json

uv run yosoi recipe inspect "$RECIPE"
uv run yosoi recipe check "$RECIPE" --json
uv run yosoi recipe install "$RECIPE" --cache-dir "$CACHE" --json

RECIPE_ID=$(python -c "import json; print(json.load(open('$RECIPE'))['recipe_id'])")
echo "recipe=$RECIPE"
echo "recipe_id=$RECIPE_ID"
echo "cache_dir=$CACHE"
echo "gh ref example: gh:owner/yosoi-recipes/recipes/example.com/products/v1/recipe.json@main"
echo "gist publish example: GITHUB_TOKEN=... uv run yosoi recipe gist $RECIPE --filename product.recipe.json"
