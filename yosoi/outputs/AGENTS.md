# Outputs Module Rules

## Purpose
Transforms extracted Python dictionaries into final user-facing formats (JSON, Markdown).

## Constraints
1. **Data Immutability**: Functions in this module must format and transform data, but never mutate the original extracted dictionaries.
2. **Format Extensibility**: Keep output logic modular. If a new output format (e.g., CSV) is added, it must have its own dedicated file and be registered in `utils.py`.
3. **Selector Storage**: CSS Selectors are intended for machine reading. Always save them as JSON regardless of the user's requested content output format.
