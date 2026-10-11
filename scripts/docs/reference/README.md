# Rust SDK reference tooling

Only workspace library crates named `yosoi` or with a reserved `*-sdk` package
name and `[package.metadata.yosoi] sdk = true` enter discovery. The private
implementation modules under `crates/yosoi/src/internal` are not separate SDK
packages. `crates/yosoi` is the public facade; reachable public re-exports can
point back to their defining internal source files.

Run with Node, Git, tar and Rustup. The documentation compiler is pinned in
`toolchain.json` independently of the production compiler. Rustdoc JSON is
experimental; unsupported formats fail instead of silently degrading.

Type references in signatures use compiler identities to select the preferred
public facade export, so moving a definition between implementation crates and
private modules does not change its public signature. A same-named type with a
different compiler identity remains distinct. Trait methods attach to the
implementation's receiver identity: rustdoc may list a `From<Input>` conversion
on `Input` and omit it from the receiver's navigation list. The model indexes
receiver implementations directly and preserves the existing synthetic,
blanket, hidden, and source-evidence filters.

The 0.1.1 scoped parity contract was migrated with the browser-feature compiler
inventory at `3cd1c0aa72cefa38f4312a2897d7dfdc5e2005fb`. Each of the 944 updated
signature hashes was matched to its previously reviewed source signature:
861 retained the exact source spelling, and 83 differed only by the documented
implementation namespace relocation. Python targets, argument bindings,
defaults, units, cardinalities, mapping decisions, and semantic evidence were
preserved. The declaration count changed from 2372 to 2369 solely to remove
three previously misattributed conversion methods: `CaptureId::from` actually
belongs to `ActivityId` (`internal/types/identity.rs`), and the two
`JsonQuerySyntaxError::from` records belong to `PlanError` and `QueryError`
(`internal/documents/plan_model.rs` and `query_error.rs`). Their receiver
implementations remain inventoried wherever the receiver is public.

The SDK extraction includes private compiler records to retain conversions
whose input types are private, while the model publishes only facade-reachable
items and traits. The compiler inventory contains no `::internal` or `::__macro`
public pages. Three genuine conversions on `DocumentError`, `ParseError`, and
`SearchSendError` retain their original source signatures. This structural
migration does not replace the installed-wheel runtime and semantic CI gates.

```sh
rustup toolchain install nightly-2026-09-06 --profile minimal
cargo xtask docs reference discover
cargo xtask docs reference generate --source FULL_COMMIT --repository OWNER/REPO --sdk yosoi --version 0.1.0 --out .generated/reference-release
cargo xtask docs reference verify --dir .generated/reference-release
cargo xtask docs reference pack --dir .generated/reference-release --out .generated/reference.tar
cargo xtask docs check
node scripts/docs/reference/compiler-fixture.mjs
```

Generation extracts a fresh exact Git snapshot, compiles with one Cargo worker,
and records SDK package version, source SHA, target, features, compiler,
generator digest and localization provenance. A version directory is immutable:
choose a new output directory to regenerate. `--offline` is optional for warm
local caches. `--toolchain nightly` is accepted only when its compiler hash
matches the pin. Imported `--from-json` content is preview-only.

The reusable `.github/workflows/rust-api-reference.yml` accepts source_commit,
version, sdk, locales and preview. Call it from a tag release workflow with
`preview: false` and the tag's full commit. Its compilation job has read-only
permissions; a separate job attests the deterministic archive. Application
credentials are not passed to either job. The workflow definition is a spike;
it has not been run on hosted Actions.

Verify the signed archive AND its extracted directory before promotion:

```sh
cargo xtask docs reference verify-attestation --dir EXTRACTED_REFERENCE --archive reference.tar --bundle ATTESTATION_BUNDLE --repository OWNER/REPO --signer-workflow OWNER/REPO/.github/workflows/rust-api-reference.yml
```

The verifier binds the directory to the archive bytes, checks the expected
repository/workflow and enforces the source SHA. Checksums alone are not signed
provenance. Local preview metadata says `unsigned-preview`; release metadata
says `pending-attestation` until the external verification gate succeeds.
GitHub's private-repository attestation availability depends on the account
plan; resolve that before enabling the release caller. No publishing or signing
was performed by this spike.

## Frontend artifact contract

Artifacts contain manifest.json, provenance.json and `<locale>/pages/<slug>.json`.
A small catalog identifies latest and maps each version to `{ sourceCommit,
manifest: { repository, commit, path, sha256 } }`. The manifest pointer's commit
is the **artifact storage commit**, distinct from the code's source commit.
Use an immutable GitHub artifact branch/repository commit for stored content.
Do not point artifact URLs at a source commit that does not contain artifacts.

The current local catalog is an explicit preview adapter: its pointers are
never eligible for publication. CascadingLabsFE `prepareRustReference` reads
`.generated/rust-reference/catalog.json` and `versions/<version>` from this
workspace, copies only latest into its build inputs, and keeps historical
content in this workspace. The loopback server lazily serves historical bytes;
the same client can fetch commit-pinned raw GitHub URLs outside demo mode.
Publishing and release-catalog promotion remain a separate reviewed rollout.

Locale overlays key prose to semantic item IDs and original docs digests.
Signatures, examples and source spans stay compiler-derived. Missing prose
falls back explicitly to English; stale overlays fail. Translation-overlay validation is covered by `reference.test.mjs`.
