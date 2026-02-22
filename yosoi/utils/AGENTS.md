# Utils Module Rules

## Purpose
Shared, globally accessible, stateless pure functions and helpers.

## Constraints
1. **Pure Functions Only**: Code here must have no side-effects (exceptions allowed for logging).
2. **No Core Dependencies**: Never import from `yosoi.core` to prevent circular dependencies.
3. **Mandatory Reuse**:
   - Network failure? Use `retry.get_retryer`.
   - Need HTTP headers? Use `headers.UserAgentRotator`.
   - Loading AI text? Use `prompts.load_prompt`.
4. **Exception Handling**: Define and use custom subclasses of `YosoiError` (found in `exceptions.py`) rather than raising generic `Exception`.
