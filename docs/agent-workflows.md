# Agent workflows

Yosoi ships agent-facing workflow assets so coding agents can use the same safe fetch, crawl, search, and research guidance as the repo.

Install assets with:

```bash
# Try project-local assets first, useful inside a repo/worktree.
uvx yosoi agents install --scope project --target pi --force

# Promote/update user-global assets when ready.
uvx yosoi agents update --target pi
uvx yosoi agents install --target agents
```

Targets:

| Target | User-scope skills | Project-scope skills | Extra assets |
| --- | --- | --- | --- |
| `pi` | `~/.pi/agent/skills/` | `./.agents/skills/` | user: `~/.pi/agent/extensions/yosoi-workflows.ts`; project: `./.pi/extensions/yosoi-workflows.ts` |
| `agents` | `~/.agents/skills/` | `./.agents/skills/` | none |
| `claude` | `~/.claude/skills/` | `./.claude/skills/` | none |
| `codex` | `~/.codex/skills/` | `./.codex/skills/` | none |
| `opencode` | `~/.config/opencode/skills/` | `./.config/opencode/skills/` | none |
| `all` | all targets above | all targets above | Pi extension for `pi` |

Installed skills:

- `yosoi-web-workflows` — choose the right Yosoi search/fetch/crawl/research workflow;
- `yosoi-fetch` — bounded page evidence acquisition without scraping;
- `yosoi-research-frontier` — exploratory source mapping and evidence packets before deterministic scraping.

Safety behavior:

- `install` skips existing files unless `--force` is passed;
- `update` overwrites existing installed assets by design;
- `--scope user` writes global agent config under your home directory;
- `--scope project` writes repo-local assets under the current working directory;
- `--dry-run` prints what would be written without changing disk;
- `--json` emits a machine-readable install/update record.

Examples:

```bash
uvx yosoi agents install --scope project --target pi --dry-run
uvx yosoi agents install --target all --force
uvx yosoi agents update --target pi --target codex --json
```

Reload or restart the target agent after install. In Pi, run `/reload`.

Back-compatible singular alias:

```bash
uvx yosoi agent install --target pi
uvx yosoi agent update --target pi
```
