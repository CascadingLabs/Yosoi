# Published docs snapshots

`docs-publish.yml` runs for relevant main pushes, manual dispatches, or after a
successful SDK release. Every snapshot records its full Yosoi source commit and
the SDK version it documents. Docs corrections keep the SDK version and acquire
a new source identity. The version is not used as a mutable directory name.

`bundle.mjs create` exports public Markdown, assets, source-owned navigation and
validation contracts, plus the matching compiler reference. It verifies API
identity and excludes draft/private documents. `bundle.json` hashes every file.
The deterministic archive is both an SDK release asset and the frontend build
input; release publication reuses the already-built bundle.

The public `docs-artifacts` branch contains `snapshots/SOURCE/bundle.tar.gz` and
`snapshots/SOURCE/content/` for on-demand raw-file access. `catalog.json` pins
each snapshot to the artifact commit that contains it and its archive/manifest
hashes. The catalog commit is separate from that artifact commit. Only the
catalog's latest pointer moves. Existing snapshots cannot be overwritten.
Serialized publication checks source ancestry so retrying an older source cannot
promote it over a newer snapshot. The mutable catalog is resolved once per build;
all subsequent downloads use immutable commit URLs.

The archive manifest includes version-local navigation and page checksums. Old
authored pages fetch as Markdown; API pages fetch as generated JSON and render
with the frontend's existing reference renderer. No historical bundle is
downloaded or imported into the frontend build. The frontend bundles only the
latest content and a small version registry.

Publish the artifact and catalog before dispatching the frontend update. A
dispatch failure can be retried independently without rebuilding the SDK. Git
integration deploys the frontend's pointer update through Cloudflare Pages.
`DOCS_DEPLOY_TOKEN` is the existing cross-repo credential; Cloudflare credentials
are not needed for this path. First publish a snapshot from reviewed Yosoi main,
then land the new frontend build command. Ordinary pushes and docs updates use
the same Cloudflare build.
