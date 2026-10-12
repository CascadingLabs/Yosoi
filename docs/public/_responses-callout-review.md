# Responses callout spike receipt

- SDK source base: `82a54f47c778b0a6e59380be03d5d09913fb3e62` (0.2.1), with existing default-workspace documentation changes preserved.
- Local preview reference profile: cached Rust API source `e3df268213c60378ee923a838b24be05d0954233`; no Rust feature profile was rebuilt for this frontend spike.
- Snippet identity: both language fences in `sdk/responses.md`, page SHA-256 `32747f008d733cf1bdaa4d38bf077e18516afabdaf8692f3b4c494515718f790`.
- Change: annotation comments only. Existing example calls, branches and outcome explanations retain their behavior. Frontend enhancement removes annotation comments from displayed and copied code.
- Local verification: six markers on the live SDK Responses page; light/dark popover rendering; toggle and Escape dismissal; query-driven language selection and reload; persistent mobile horizontal scroll control.
- Focused frontend checks: four tests across code-contract, code-variants and navigation-browser fixtures passed, including annotation snapshots, archive code enhancement, generic tab labels, copy output and print notes. Scoped formatting, lint and TypeScript checks passed.
- Public Markdown formatting check passed. No SDK execution, full site build, hosted CI, publication or deployment was performed for this spike.

This developer-only file is excluded from public documentation by its underscore prefix.
