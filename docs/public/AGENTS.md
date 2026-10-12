# Public docs source contract

## Public authoring rules

- Write new public learning pages in plain Markdown. Do not add MDX, JSX, imports or executable components. Existing draft fixtures are not authoring examples.
- Base claims and examples on the selected current public Rust facade and Python package. Inspect implementations when public declarations do not establish behavior. Design notebooks, old examples and reference inventories alone do not prove current runtime behavior.
- Record the exact source revision, feature profile, snippet identity and validation in a maintainer review receipt. Keep these work records outside public prose. Recheck examples when their source changes.
- Organize learning by concepts and tasks, not by language. Explain shared behavior once. Keep language syntax, execution instructions and capability differences with the corresponding example.
- Teach through several small code examples and concrete walkthroughs. Start with a minimal useful task, show how to inspect the result, then cover a meaningful variation or failure. Explain conceptual sequences as numbered steps or short paragraphs. Do not put pseudocode, proposed APIs or invented helper calls in code fences.
- Pair Rust and Python examples for the same input and intended outcome wherever both interfaces support the task. Do not invent parity or an API to fill a panel. Explain unsupported capabilities explicitly.
- Author an H2 Example group with H3 Rust and Python sections containing code and short explanations. Repeat groups as needed. Use a separate H2 Install or Commands group with H3 Cargo and uv sections. These headings are readable without frontend enhancement.
- The frontend's clickable changer must select code and its explanation together, work for static and archived pages, and display both variants without JavaScript. Verify it in static and archived rendering.
- Use Cargo for Rust project commands and uv for Python project commands. Use `uv add`, `uv run python` and project-appropriate `uv sync`. Do not give pip installation instructions. Development checks should use `uv run --no-sync` when the existing environment is synchronized.
- Use simple words, short connected paragraphs and concrete names. Explain important calls, inputs and outcomes immediately below their code. Avoid jargon, repeated introductions and promotional language.
- Do not use em dashes in authored prose. Use periods, commas, colons or parentheses. Ordinary hyphens in names and code remain valid.
- Separate construction, execution, validation, evidence completeness and business completion. Explain missing data, partial results and unknown effects where the task can encounter them.
- For browser tasks, explain Session lifetime, tab identity, Work authority, execution capacity and cleanup only to the depth the task needs. Preserve browser sandbox and isolation requirements.
- Runnable examples use public APIs and real error propagation. Do not use panic-prone shortcuts in application code. Visible assertions are appropriate in self-contained demonstration checks.
- Natural-language field descriptions do not automatically discover elements unless the current API explicitly does so. Fixture selectors belong to controlled input; site recipes need supported discovery or explicit site bindings.
- Concept pages explain meanings and boundaries. Cookbook contains focused guides and complete recipes with named steps, typed records and visible checks of the intended result.
- Keep new skeletons `draft: true` until required claims, examples and links pass review. Do not publish maintainer TODOs, proposed APIs or placeholders.
- Keep existing public URLs and immutable historical bundles stable while consolidating pages. Only the integration owner changes live navigation. Reference and release-note work stays with its assigned owners.

This file is developer-only and must never become a published page. The collection includes eligible `.md` and `.mdx` files recursively, excluding `AGENTS.md`, `README.md`, names beginning with `_`, and pages with YAML `draft: true`.

Page frontmatter may contain `title`, `description`, `order`, and `draft`. Release pages under `releases/` may also contain the string fields `version`, `date`, `channel`, and optional `previous`; the public manifest carries these values on the corresponding page record. Release tooling validates their release-specific values and coherence: channels are `preview` or `recommended`, dates are real calendar dates in `YYYY-MM-DD`, and beta versions use `0.MINOR.PATCH` with MINOR from 1 through 100000 and PATCH from 0 through 10000. `previous` is an explicit earlier comparison baseline and is omitted only for the first tracked release. Version dots map to hyphens in filenames, for example `releases/0-2-0.md`.

A root `index.md` or `index.mdx` is required. Routes use lowercase kebab-case path segments; `index.md` maps to its directory route, the root maps to `/`, and other routes omit `.md` or `.mdx` without a trailing slash. Pages have no IDs or redirects.

Legacy MDX fixtures stay draft-only. New learning pages use plain Markdown.

## Navigation metadata

Numbered release candidates additionally accept version `0.MINOR.PATCH-rc.N`
with positive, unpadded N. Their filenames replace dots with hyphens, for example
`releases/0-1-0-rc-1.md`. Candidates sort before the corresponding final version
and use the `preview` channel.

`_navigation.json` is tracked source configuration, excluded from published pages and assets. Its version-1 `sections` array defines sidebar labels and order. A section selects explicit `pages`, an automatically discovered `directory`, or `generated: "rust-api"`. Page entries can be filenames or `{ "file": "index.md", "label": "Overview" }`. Directory sections may provide an `order` array of relative Markdown filenames; newly discovered pages follow those entries. Overview pages remain first. The section list is authoritative: omitted sections or explicit pages stay out of the sidebar; their URLs remain published. Directory order arrays prioritize rather than hide pages. JSON comments and trailing commas are supported.

Yosoi CI and frontend preparation share the validation contract for this metadata and records its SHA-256 plus the resolved navigation in the ignored snapshot. Missing/draft/private page references and duplicate assignments are errors. Do not put CSS, components, or generated API signatures in the navigation file.

The sidebar has one Reference section with nested Rust and Python sections. A section may use a nested `sections` array instead of selecting pages, a directory, or generated content. The same validation and duplicate-page checks apply across every nesting level. `generated: "rust-api"` uses compiler-derived Rust declarations, while `directory: "python-api"` selects Python Markdown generated during validation, local preparation, and bundle publication. Within the Rust reference, module containers and kind categories are collapsible; individual symbols are plain links. Kind categories are Modules, Types, Functions, Macros, Constants, and Exports. Keep canonical Rust item URLs unchanged.

`scripts/docs/python_reference.py` parses Python source with the standard-library AST; it does not import the SDK or execute the native extension. It accounts for every package `__all__` export and publishes source-declared symbols from public modules, organized into Types, Functions, Aliases, and Constants. Preserve annotations, defaults, async/generic signatures, declared class fields/methods, and source locations. Do not invent missing docstrings or imply that inherited/dynamically generated Pydantic members were extracted. Generated `python-api/` pages belong only in staging directories and immutable bundles, not authored source. Bundle publication extracts the Python files and generator from the exact selected Git commit and pins source links to that commit.

The `releases` directory has release-specific navigation: its overview stays first, only final numbered versions appear, and entries sort numerically newest first. Group patches under collapsible major/minor families such as `0.2.x`; individual links use only the full version, such as `0.2.1`. These navigation labels do not rename page titles or URLs. RC pages remain published at their existing URLs but stay out of this sidebar.

Python symbol navigation carries declaration-kind metadata derived from its generated category paths: Types are classes, Functions are functions, Aliases are type aliases, and Constants are constants. Overview pages and category containers have no symbol kind. The frontend uses this metadata for the same icons, truncation, hover titles, and accessible names as Rust; an icon describes a declaration, not runtime type enforcement.

The release overview is generated by `scripts/releases/release.py history`; edit its explanatory copy in `HISTORY_GUIDE`, then regenerate rather than editing the checksummed index by hand. Entries show version, date, and a concise description of the change. Legacy `channel` metadata remains accepted for release-tool compatibility but must not produce Preview/Recommended badges or public channel explanations. Keep the beta notice separate from universal major/minor/patch and RC definitions.

## CI and formatting

Run `vpr check` from `scripts/docs` before pushing public docs; run `vpr fmt` there to fix formatting. The gate checks public Markdown formatting, frontmatter, paths, links/assets, navigation, headings, and native Markdown rendering. Keep work-in-progress MDX marked `draft: true` until frontend MDX ingestion is supported.
