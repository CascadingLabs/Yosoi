# Public documentation gate

From this directory, run `vp install --frozen-lockfile` then `vpr check`. Use `vpr fmt` to fix formatting. The same command runs in the Yosoi **Docs CI result** job on every pull request and push to main. Require that check in branch protection after the workflow is merged.

Oxfmt checks published Markdown and `_navigation.json`. JSON comments and trailing commas are supported. The gate validates frontmatter, public paths, relative links/assets, navigation selectors, and the single-title convention, then renders every public Markdown body with Sätteri. The frontend preparation task imports these same content/navigation contracts. It does not fetch remote websites, compile Rust, or publish artifacts. Compiler-generated API validation remains in the separate reference workflow. Visual design remains a frontend/browser check.

A removed navigation section stays hidden while its Markdown pages remain available by URL. Directory sections discover new pages. `draft: true`, `_` paths, AGENTS.md, and README.md are excluded. MDX publication is not enabled yet; the old component demo is explicitly draft so unsupported pages cannot disappear silently from the frontend.
