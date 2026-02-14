# Utils Agent Guide

## Purpose
The `utils` directory holds shared, stateless functionality that doesn't fit into the core domain objects.

## When to put code here?
- **Generic Helpers**: String manipulation, file I/O, URL normalization.
- **Shared Constants**: If they are used across multiple modules.
- **No Side Effects**: Utils should generally be pure functions.

## What NOT to put here
- **Business Logic**: Core domain rules (like how to validate a selector) belong in their respective modules.
- **Stateful Classes**: If it needs to hold state, it's probably a Service or a Model, not a Util.
