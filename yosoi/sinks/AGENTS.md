# Sinks Module Rules

## Purpose
Pluggable, append-only storage for extracted content. A `ContentSink` is the seam between
Yosoi's extraction output and a downstream consumer's database of choice. This is distinct
from `yosoi/storage/`, which handles local-filesystem persistence of selectors/debug data.

## Constraints
1. **Narrow interface**: The `ContentSink` Protocol stays append-only and content-only —
   `write`, `read_by_url`, `read_by_time`, `close`. No entity resolution, canonicalisation, or
   consumer-specific concepts; those live in the downstream repo.
2. **Append-only**: `write` always inserts a new record; never update or overwrite. `scraped_at`
   distinguishes versions.
3. **Lazy drivers**: Database drivers are optional extras. Import them lazily inside the backend
   (never at module top level) and raise a helpful "install yosoi[<extra>]" message via
   `_internal.missing_dependency`. Core must import only the interface + record contract.
4. **Record contract**: `ContentRecord` (`url`, `content`, `scraped_at`, `source`) is the public
   output shape. Index on `url` and `scraped_at` in every backend.
5. **Async + UTC**: All sink methods are async. Normalise timestamps with `_internal.to_utc`
   before storing or querying so ranges are consistent across backends.

## Local dev / testing
Postgres and Mongo round-trips live in `tests/integration/sinks/`. Bring up a local stack with
`docker compose -f docker-compose.sinks.yml up -d` and point the tests at it via
`YOSOI_TEST_POSTGRES_DSN` / `YOSOI_TEST_MONGO_URI` (see the compose file header). Without those env
vars the tests fall back to ephemeral `testcontainers` instances, and skip entirely when neither a
DSN nor Docker is available. SQLite needs nothing — it is covered by `tests/unit/sinks/`.
