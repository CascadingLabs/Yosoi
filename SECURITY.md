# Security Policy

## Reporting a vulnerability

Do not report security vulnerabilities through public issues or discussions.

Report a vulnerability privately by emailing [contact@cascadinglabs.com](mailto:contact@cascadinglabs.com) or contacting a Cascading Labs maintainer directly. Include the affected revision, potential impact, reproduction steps or a proof of concept, and any suggested mitigation.

The maintainers will acknowledge the report, investigate it, and coordinate disclosure when appropriate.

## Scope

This policy covers Yosoi Oxide. The project is currently private, pre-release software with no supported production version.

## Response-body dependencies

Direct HTTP response decoding uses `async-compression` with default features disabled and only the
Tokio gzip, Brotli, and zlib decoders enabled. `tokio-util` supplies only the I/O and runtime
adapters. Dependency policy is enforced through the workspace lockfile and `cargo deny`; changes to
these features require review for decompression expansion, malformed-input handling, and advisory
status. Transport error sources must be stripped of request URIs before retention or reporting.
