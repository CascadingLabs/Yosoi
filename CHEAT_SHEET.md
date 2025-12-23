# QUICK REFERENCE - Dev Tools Cheat Sheet

## FIRST TIME SETUP
```bash
uv sync --group dev
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
uv run pre-commit run --all-files
```

## DAILY COMMANDS

### Ruff (Linter + Formatter)
```bash
uv run ruff check .                    # Check for issues
uv run ruff check . --fix              # Auto-fix issues
uv run ruff format .                   # Format code
uv run ruff check . --watch            # Watch mode
```

### Mypy (Type Checker)
```bash
uv run mypy main.py                    # Check one file
uv run mypy .                          # Check all files
uv run mypy --strict main.py           # Strict mode
uv run mypy --install-types            # Install missing type stubs
```

### Pre-commit (Git Hooks)
```bash
uv run pre-commit run --all-files      # Run all hooks
uv run pre-commit run ruff             # Run specific hook
uv run pre-commit autoupdate           # Update hook versions
git commit --no-verify                 # Skip hooks (emergency!)
```

### Commitizen (Conventional Commits)
```bash
uv run cz commit                       # Interactive commit
uv run cz bump                         # Version bump + changelog
uv run cz changelog                    # Generate changelog
uv run cz version                      # Show current version
```

## COMMIT MESSAGE FORMAT
`<type>(<scope>): <subject>`

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`

**Examples:**
- ✅ `feat: add AI selector discovery`
- ✅ `fix: handle missing article tags`
- ✅ `docs: update README`
- ✅ `refactor: split into modules`
- ❌ `Added new feature` (missing type)
- ❌ `feat add feature` (missing colon)

## COMMON WORKFLOWS

### Making Changes
1. Edit files
2. `git add <files>`
3. `uv run cz commit` (or `git commit -m "type: message"`)
4. Hooks run automatically
5. Fix any issues, re-commit

### Checking Code
```bash
uv run ruff check . --fix              # Fix style issues
uv run mypy .                          # Check types
uv run pre-commit run --all-files      # Run all checks
```

### Releasing
```bash
uv run cz bump                         # Bump version
git push                               # Push commits
git push --tags                        # Push tags
```

## HOOK STAGES
- **pre-commit:** Runs before commit
- **commit-msg:** Validates commit message
- **pre-push:** Runs before push (not configured)

## SKIPPING HOOKS
```bash
git commit --no-verify                 # Skip all hooks
SKIP=mypy git commit -m "..."          # Skip mypy only
SKIP=ruff,mypy git commit              # Skip multiple
```

## CONFIGURATION FILES
- `pyproject.toml` - Ruff, Mypy, Commitizen config
- `.pre-commit-config.yaml` - Pre-commit hooks
