# Storage Module Rules

## Purpose
Handles local filesystem persistence, including saving generated selectors, tracking LLM usage, and managing debug dumps.

## Constraints
1. **Path Resolution**: Never hardcode relative paths. Always use path resolution utilities from `yosoi.utils.files` (e.g., `get_project_root()`).
2. **Safe I/O**: Ensure directory trees exist (`os.makedirs(..., exist_ok=True)`) before writing files.
3. **Encoding**: Always specify `encoding='utf-8'` when opening or writing files to prevent cross-platform crashes.
4. **Separation of Concerns**: Do not format content for the user here. Defer formatting to `yosoi.outputs`; this module only handles the physical writing/reading of data.
