# Yosoi policy files

Yosoi policy files are plain JSON or YAML using the `Policy` shape directly. For YAML editor completion, start files with:

```yaml
# yaml-language-server: $schema=https://cascadinglabs.com/yosoi/schemas/policy.schema.json
```

Create starter files:

```bash
yosoi policy init --local     # .yosoi/policy.yaml
yosoi policy init --global    # ~/.config/yosoi/policy.yaml
yosoi policy init --global --local
```

Print the schema for publishing or local editor wiring:

```bash
yosoi policy schema > policy.schema.json
```

Policy precedence is: environment, discovered global/project files, then explicit `--policy` layers, with later layers overriding earlier fields.

Search uses the same policy tree. Put durable defaults under `search`, then let
direct CLI flags such as `--limit` or `--backend` override them for one run:

```yaml
search:
  provider: ddgs
  backend: google,bing,brave
  region: us-en
  safesearch: "moderate"
  max_results: 10
  page: 1
```

The environment layer also reads `YOSOI_SEARCH_BACKEND`,
`YOSOI_SEARCH_REGION`, `YOSOI_SEARCH_SAFESEARCH`,
`YOSOI_SEARCH_MAX_RESULTS`, `YOSOI_SEARCH_PAGE`, and
`YOSOI_SEARCH_TIMELIMIT`.

Recipe loading uses the `recipe` policy block. Local recipe files are allowed by
default; remote recipes are deny-by-default unless you allow exact hosts or
GitHub owners. Recipe ids and contract fingerprints are additional allowlists:
when set, they must also match.

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

See [`recipes.md`](recipes.md) for CLI/API examples and remote trust behavior.
