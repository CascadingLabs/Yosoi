Thank you for your interest in contributing to Yosoi! Below you'll find information about our development process and tools.

## Developing Yosoi
<TODO>
## Code Style
<TODO>
## Development Tools

Yosoi includes a complete development toolchain:

### Setup Dev Environment

```bash
# Install with dev dependencies
uv sync --group dev

# Install pre-commit hooks
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg

# Run all checks
uv run pre-commit run --all-files
```

### Available Tools

| Tool | Purpose | Command |
|------|---------|---------|
| **Ruff** | Linting & Formatting | `uv run ruff check .` |
| **Mypy** | Type Checking | `uv run mypy .` |
| **Pre-commit** | Git Hooks | `uv run pre-commit run --all-files` |
| **Commitizen** | Conventional Commits | `uv run cz commit` |

See [CHEAT_SHEET.md](CHEAT_SHEET.md) for detailed commands.

### Commit Guidelines

Use conventional commits:

```bash
# Interactive commit
uv run cz commit

# Manual commit (must follow format)
git commit -m "feat: add new selector discovery feature"
git commit -m "fix: handle missing author tags"
git commit -m "docs: update README with examples"
```

**Commit Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance
