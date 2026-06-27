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
