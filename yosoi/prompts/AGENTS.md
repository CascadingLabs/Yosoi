# Prompts Module Rules

## Purpose
Holds raw markdown files used as system and user prompts for AI agents.

## Constraints
1. **Markdown Only**: Only `.md` files belong in this directory. Do not place Python code here.
2. **Variable Injection**: Ensure prompt variables use strict brace syntax (e.g., `{url}`, `{html}`) so they can be securely interpolated via standard Python `.format()`.
3. **Brevity**: Keep prompts concise and highly constrained to save tokens and limit LLM hallucinations.
