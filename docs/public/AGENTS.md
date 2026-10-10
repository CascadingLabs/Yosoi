# Public docs source contract

This file is developer-only and must never become a published page. The collection includes eligible `.md` and `.mdx` files recursively, excluding `AGENTS.md`, `README.md`, names beginning with `_`, and pages with YAML `draft: true`.

Page frontmatter may contain `title`, `description`, `order`, and `draft`. Release pages under `releases/` may also contain the string fields `version`, `date`, `channel`, and optional `previous`; the public manifest carries these values on the corresponding page record. Release tooling validates their release-specific values and coherence: channels are `preview` or `recommended`, dates are real calendar dates in `YYYY-MM-DD`, and beta versions use `0.MINOR.PATCH` with MINOR from 1 through 100000 and PATCH from 0 through 10000. `previous` is an explicit earlier comparison baseline and is omitted only for the first tracked release. Version dots map to hyphens in filenames, for example `releases/0-2-0.md`.

A root `index.md` or `index.mdx` is required. Routes use lowercase kebab-case path segments; `index.md` maps to its directory route, the root maps to `/`, and other routes omit `.md` or `.mdx` without a trailing slash. Pages have no IDs or redirects.

MDX fixtures use only the documented `Callout` form with a `title` attribute and Markdown body.

## Navigation metadata

Numbered release candidates additionally accept version `0.MINOR.PATCH-rc.N`
with positive, unpadded N. Their filenames replace dots with hyphens, for example
`releases/0-1-0-rc-1.md`. Candidates sort before the corresponding final version
and use the `preview` channel.

`_navigation.json` is tracked source configuration, excluded from published pages and assets. Its version-1 `sections` array defines sidebar labels and order. A section selects explicit `pages`, an automatically discovered `directory`, or `generated: "rust-api"`. Page entries can be filenames or `{ "file": "index.md", "label": "Overview" }`. Directory sections may provide an `order` array of relative Markdown filenames; newly discovered pages follow those entries. Overview pages remain first. The section list is authoritative: omitted sections or explicit pages stay out of the sidebar; their URLs remain published. Directory order arrays prioritize rather than hide pages. JSON comments and trailing commas are supported.

Yosoi CI and frontend preparation share the validation contract for this metadata and records its SHA-256 plus the resolved navigation in the ignored snapshot. Missing/draft/private page references and duplicate assignments are errors. Do not put CSS, components, or generated API signatures in the navigation file.

## CI and formatting

Run `vpr check` from `scripts/docs` before pushing public docs; run `vpr fmt` there to fix formatting. The gate checks public Markdown formatting, frontmatter, paths, links/assets, navigation, headings, and native Markdown rendering. Keep work-in-progress MDX marked `draft: true` until frontend MDX ingestion is supported.
