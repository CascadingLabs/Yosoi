# Release notes

<!-- prettier-ignore-start -->

This section records the user-visible changes, compatibility impact, and upgrade actions for each published Yosoi release.

> **Yosoi is currently in beta.** Versions below `1.0.0` have an API that can still change, including breaking changes in minor releases. Read the upgrade notes before updating. `1.0.0` will mark the first stable release.

## Version numbers

Versions use `MAJOR.MINOR.PATCH`. For example, `0.2.1` has major `0`, minor `2`, and patch `1`.

| Part | Meaning |
| --- | --- |
| Major | Breaking API changes, such as `1.4.2` → `2.0.0`. Minor and patch reset to `0`. |
| Minor | New features compatible with the existing API, such as `1.4.2` → `1.5.0`. Patch resets to `0`. |
| Patch | Compatible bug fixes and hotfixes, such as `1.4.2` → `1.4.3`. |

These are the [Semantic Versioning](https://semver.org/) conventions for a stable API. A minor version does not itself mean beta.

A suffix such as `-rc.1` means **release candidate**: a version being evaluated before its final numbered release. Candidate notes remain accessible by direct link but are omitted from the release list, sidebar, and version picker.

<!-- release-history:generated-begin -->

## Releases

- [0.2.0](0-2-0.md) · 2026-10-11 — Rust and Python browser workflows with reusable Flows, typed assertions, and explicit ownership.
- [0.1.2](0-1-2.md) · 2026-10-11 — An internal browser controller and release checks that validate wheels before publication.
- [0.1.1](0-1-1.md) · 2026-10-11 — One modular runtime crate, an optional CLI, and unchanged Rust and Python SDK calls.
- [0.1.0](0-1-0.md) · 2026-10-10 — The first public Rust and Python SDK beta, with versioned docs and Chromium runtime images.

<!-- release-history:generated-end sha256=e114c78d99140c9d95ded12e1b2b3c1b7fe993ddd6d4b99a6f8996fcc0b1f78f -->

<!-- prettier-ignore-end -->
