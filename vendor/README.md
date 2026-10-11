# Vendored browser sources

The Chromiumoxide controller and generated Chrome DevTools Protocol bindings
are private Rust modules included in the published `yosoi` crate's optional
`browser` feature:

```text
Yosoi SDK → private browser adapter → Chromiumoxide module → CDP module
```

Their source, fixtures, license notices, and maintenance records live under
[`crates/yosoi/src/internal/browser/vendor/`](../crates/yosoi/src/internal/browser/vendor/).
The controller's upstream base and local patch queue are in its
[`VENDORING.md`](../crates/yosoi/src/internal/browser/vendor/chromiumoxide/VENDORING.md).
The generated schema's provenance and regeneration procedure are in its
[`VENDORING.md`](../crates/yosoi/src/internal/browser/vendor/chromiumoxide_cdp/VENDORING.md).

The source directories have no independent Cargo manifests or public Rust
facades. Applications use the `yosoi` SDK API.
