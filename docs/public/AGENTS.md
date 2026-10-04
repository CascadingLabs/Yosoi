# Public docs source contract

This file is developer-only and must never become a published page. The collection includes eligible `.md` and `.mdx` files recursively, excluding `AGENTS.md`, `README.md`, names beginning with `_`, and pages with YAML `draft: true`.

Page frontmatter may contain `title`, `description`, `order`, and `draft`. A root `index.md` or `index.mdx` is required. Routes use lowercase kebab-case path segments; `index.md` maps to its directory route, the root maps to `/`, and other routes omit `.md` or `.mdx` without a trailing slash. Pages have no IDs or redirects.

MDX fixtures use only the documented `Callout` form with a `title` attribute and Markdown body.
