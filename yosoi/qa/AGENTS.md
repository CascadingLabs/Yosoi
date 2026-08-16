# QA Runtime Rules

## Purpose

`yosoi.qa` is the first consumer of `yosoi.observations`. It owns QA task semantics, live-session composition, provider-facing tools, prompts, findings, and reports. It does not own the reusable observation/index kernel.

## Dependency boundary

- QA may import `yosoi.observations` and existing Yosoi acquisition/provider/verification abstractions.
- `yosoi.observations` and `yosoi.core` must never import `yosoi.qa`.
- Do not create a second browser pool, provider configuration system, selector validator, or persistence architecture.
- Use existing `ModelPolicy` when provider wiring begins.
- The initial runtime is opt-in, read-only, and non-authoritative.
- Tool calls must be bounded by turn, token, byte, and item budgets.

## Current phase

This package contains contracts and fail-closed mocks only. A `yosoi qa` help/status shell frames the arm, but it cannot run QA. The package is deliberately not exported from `yosoi`, mounted as provider tools, connected to VoidCrawl, or added to operations/policy.
