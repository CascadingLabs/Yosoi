# Local Docker profiles

Both builders pin the official Rust 1.99.0 Linux/amd64 image by digest, matching
the repository's development toolchain. Updated container builds and browser
certification remain pending; recorded results retain their original toolchain
and image identities in [the browser baseline](../docs/chromium-cdp-baseline.md).

The `browser/` and `browser-stealth/` Docker profiles retain their sandbox and
source identities. Their legacy script orchestrators have been retired. Building
these templates requires a sanitized context containing the complete workspace
under `YosoiOxide/` and the browser Docker files at `docker/browser/`; exclude VCS
state, generated output, credentials, and local configuration. These templates
are not a current browser certification entry point. Consult
`docs/chromium-cdp-baseline.md` before preparing a new certification.
