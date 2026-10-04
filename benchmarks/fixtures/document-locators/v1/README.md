# Document locator fixtures

The golden tier contains small, committed HTML, XML, JSON, decoded-text,
rendered-DOM, and accessibility inputs. `manifest.json` pins file paths, sizes,
hashes, schemas, and provenance. `matrix.json` retains the benchmark cases and
expected locator values; Rust regression tests own semantic correctness.

## Integrity

```sh
cargo xtask fixtures verify
```

The native checker rejects unknown manifest/matrix schemas, duplicate fixture
IDs or paths, unsafe paths, missing files, changed byte counts or hashes, and
matrix references to unknown fixtures. It verifies the advanced archive and any
already materialized advanced files. The old Python oracle and fixture-generation
workflows are retired.

## Advanced corpus

The compressed `advanced/source.tar.gz` contains all twelve pinned files,
including the existing normalized rendered-DOM bytes. Extraction uses the pinned
bytes directly; no browser, CDP session, network fetch, or normalization pipeline
is required. File paths, contents, hashes, expected values, licenses, and capture
provenance are unchanged by the archive repack.

The archive is 8,682,249 bytes, SHA-256
`47b96567eb497d1de0e054fac518bd7664ec03b37038e0efb57ccb2699e9bdde`. The authoritative archive and
member identities live in `advanced/manifest.json`.

```sh
cargo xtask fixtures materialize
cargo xtask fixtures verify
```

Extraction verifies the compressed archive, exact regular-file membership, and
each expanded file before publishing `advanced/materialized/`. Existing output
must already match every pin. The materialized directory remains ignored.
Use `YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR` to point tests and benchmarks at another
verified copy. See `advanced/ATTRIBUTION.md` for upstream notices.
