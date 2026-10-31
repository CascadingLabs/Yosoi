# Published docs snapshots

`docs-publish.yml` runs only through manual dispatch or a reusable call after a
successful SDK release. Main pushes do not publish docs automatically. Use
**Publish Yosoi docs** → **Run workflow** on `main` for standalone docs corrections.
Every snapshot records its full Yosoi source commit and
the SDK version it documents. Docs corrections keep the SDK version and acquire
a new source identity. The version is not used as a mutable directory name.

Standalone manual publication requires `refs/heads/main`. Reusable calls from
release CD may publish their validated tag commit; the release workflow verifies
that its own revision matches that tag before allowing registry publication.

`bundle.mjs create` exports public Markdown, assets, source-owned navigation and
validation contracts, plus the matching compiler reference. It verifies API
identity and excludes draft/private documents. `bundle.json` hashes every file.
The deterministic archive is both an SDK release asset and the frontend build
input; release publication reuses the already-built bundle.

The Yosoi `main` trunk contains `snapshots/SOURCE/bundle.tar.gz` and
`snapshots/SOURCE/content/` for on-demand raw-file access. `catalog.json` pins
each snapshot to the artifact commit that contains it and its archive/manifest
hashes. The catalog commit is separate from that artifact commit. Only the
catalog's latest pointer moves. Existing snapshots cannot be overwritten.
Serialized publication checks source ancestry so retrying an older source cannot
promote it over a newer snapshot. The mutable catalog is resolved once per build;
all subsequent downloads use immutable commit URLs.

Publication checks out the current `main`, appends the snapshot and catalog,
and pushes forward without force. A concurrent source push rejects publication
instead of overwriting it; rerun the workflow. Publishing artifacts does not start
another publisher. Historical artifact commits remain ancestors of `main`, keeping
existing commit-pinned archive URLs valid without a separate artifact branch.

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
