# Contributing to Yosoi

Thanks for your interest in contributing to Yosoi! This guide covers how to get set up and what we expect from pull requests.

## Objectives

Yosoi is an AI-powered tool that discovers resilient selectors for web scraping. The core philosophy is "Discover once, scrape forever." Contributions that improve selector discovery accuracy, add new LLM provider support, improve validation, or expand test coverage are welcome.

## Clone & Setup

```bash
git clone https://github.com/CascadingLabs/Yosoi.git
cd Yosoi
uv sync --all-groups
```

**Prerequisites:**

| Tool | Version | Install |
|------|---------|---------|
| Python | >= 3.10 | System or [mise](https://mise.jdx.dev) |
| uv | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

### Install pre-commit hooks

```bash
uvx prek install
```

[Prek](https://github.com/thesuperzapper/prek) is a Rust-based pre-commit runner that executes git hooks automatically on every `git commit`, catching issues before they reach CI. It reads the same `.pre-commit-config.yaml` format. In this repo the hooks run ruff (lint + format), Pyrefly, check for secrets via gitleaks, and enforce conventional commit messages via commitizen. To run all hooks manually:

```bash
uvx prek run --all-files
```

### Run tests

```bash
uv run poe ci-test
```

### Full CI check

```bash
uv run poe ci-check
```

## Linting & Formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [Pyrefly](https://pyrefly.org/) for type checking and editor diagnostics. Config lives in `pyproject.toml`.

**Key rules:**

- Single quotes, 120-char line length
- Comprehensive rule set (ARG, ASYNC, B, C4, C901, D, E, F, I, PERF, PT, RET, RUF, SIM, UP, and more)
- Google-style docstrings
- Per-file ignores for tests, examples, and `__init__.py`
- Pyrefly with a Python 3.10 target and a migration baseline for existing findings

### Commands

| Tool | Purpose | Command |
|------|---------|---------|
| Ruff lint | Linting | `uv run ruff check .` |
| Ruff format | Formatting | `uv run ruff format .` |
| Pyrefly | Type checking | `uv run pyrefly check` |
| Prek | All hooks | `uvx prek run --all-files` |

CI runs ruff, Pyrefly, and tests on every push and PR. Your PR must pass all checks.

## Issues

We use [GitHub issue forms](https://github.com/CascadingLabs/Yosoi/issues/new/choose) for all issues. Pick the template that fits:

- **Bug Report** -something is broken or behaving unexpectedly.
- **Feature Request** -suggest a new feature or improvement.
- **Question** -ask a question about usage or internals.
- **Ticket** -internal planning ticket for tracked work.

Blank issues are disabled -please use a template so we have the context we need to help.

## Pull Request Rules

1. **Branch from `main`** -create a feature branch (`feat/...`, `fix/...`, `docs/...`).
2. **Keep PRs focused** -one logical change per PR.
3. **Pass CI** -lint, type check, and tests must all pass.
4. **Use the PR template** -every PR auto-fills a template. Fill in all sections:
   - **Intent** -what the PR does and why.
   - **Changes** -a summary of what was changed.
   - **GenAI usage** -check the box and describe how AI was used, if applicable. All AI-generated code must be reviewed line-by-line.
   - **Risks** -any risks or side effects this PR might introduce.
5. **Link an issue** -reference the issue your PR addresses with `Closes #<number>`.

### Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org/) enforced by [Commitizen](https://commitizen-tools.github.io/commitizen/):

```
feat: add new selector discovery feature
fix: handle missing author tags
docs: update README with examples
test: add integration tests for HTML parser
```

## Code Style

- Never use `unittest` -always `pytest`
- Use `tenacity` for retries -never `time.sleep()` in loops
- Always use `uv run` to execute commands -never bare `python` or `pip`
- Maintain strong typing throughout -Pyrefly is enforced

## License

Contributions are licensed under Apache-2.0, matching the project.
