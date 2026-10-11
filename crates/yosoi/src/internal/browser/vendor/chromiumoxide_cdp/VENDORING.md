# Private Chromiumoxide CDP bindings module

This private module starts from Chromiumoxide 0.9.1's generated-code
conventions and handwritten `src/lib.rs` compatibility helpers while updating
its protocol definitions to the first CAS-373 candidate. Its former standalone
distribution package was `yosoi-chromiumoxide-cdp` version
`0.10.0-yosoi.m153.1`; the Cargo manifest was removed during SDK consolidation.
The module remains inside the published `yosoi` crate and does not expose a
public Yosoi API.

The schema version `0.10.0-yosoi.m153.1` records the intentional M145-to-M153
protocol boundary. It does **not** preserve the complete M145 CDP API: Chrome
153 removed or renamed public protocol types, including the legacy
`Network.InterceptionId` used by the old controller.

- Chrome: `153.0.8010.36`
- Chromium revision: `r1681091`
- V8 revision from that Chrome tag's `DEPS` file:
  `f343157cebb388bfa416baccb5d35507e6fe8cc7`
- Controller upstream package: `chromiumoxide` 0.9.1
- `browser_protocol.pdl` and every included domain:
  `https://chromium.googlesource.com/chromium/src/+/153.0.8010.36/third_party/blink/public/devtools_protocol/`
- `js_protocol.pdl`:
  `https://chromium.googlesource.com/v8/v8/+/f343157cebb388bfa416baccb5d35507e6fe8cc7/include/js_protocol.pdl`

`PDL.SHA256` records all 54 exact inputs: the browser include manifest, its 52
domain files, and the V8 JavaScript protocol. `GENERATED.SHA256` records the
checked-in output. Verify both plus the embedded revision metadata with:

```bash
crates/yosoi/src/internal/browser/vendor/chromiumoxide_cdp/scripts/verify-generated.sh
```

The Chromium PDL inputs are redistributed under `LICENSE-CHROMIUM` and the V8
PDL input under `LICENSE-V8`. Their SHA-256 digests are respectively
`368cca1106be99d39ecd32a38d8305585d802a475effb66380b91ffc9bcf709b`
and `4af93c12062c58058378de2397dc1c92bbff9ddfb1d583a01c84127557ce97ca`.

Generation uses `chromiumoxide_pdl` 0.9.1 with experimental definitions
enabled and deprecated definitions excluded, except for the controller's
existing `Network.emulateNetworkConditions` compile-time dependency:

```rust
let mut generator = chromiumoxide_pdl::build::Generator::default();
generator.out_dir("src");
generator.allowed_deprecated_type("emulateNetworkConditions");
generator.compile_pdls(&["pdl/js_protocol.pdl", "pdl/browser_protocol.pdl"])?;
```

Do not enable every deprecated definition with this generator version. Its
event generator emits `[deprecated]` instead of `#[deprecated]` for deprecated
events. The narrow allow-list above avoids that upstream generator defect and
retains the one deprecated command compiled by the controller.

After refreshing every PDL input from the immutable sources above and updating
the version/revision metadata, regenerate and refresh the manifests:

```bash
CARGO_BUILD_JOBS=1 cargo run -p yosoi --example generate-cdp --offline --locked
(
  cd crates/yosoi/src/internal/browser/vendor/chromiumoxide_cdp
  find pdl -type f -name '*.pdl' -print0 | sort -z | xargs -0 sha256sum > PDL.SHA256
  sha256sum src/cdp.rs > GENERATED.SHA256
)
crates/yosoi/src/internal/browser/vendor/chromiumoxide_cdp/scripts/verify-generated.sh
```

Review the generated public API diff and all controller compile failures before
accepting a new version. Never patch the tagged PDL merely to restore a removed
type; adapt the controller or record a deliberate compatibility extension.

## Private module packaging in Yosoi 0.1.2

The PDL inputs and generated protocol types retain the reviewed M153 schema. The SDK generator applies a deterministic packaging adaptation: the generated `consume_event!` helper is exported only within the private browser module instead of at the crate root. This changes macro linkage, not CDP commands, events, or payloads. `GENERATED.SHA256` records the adapted file; the original generator output digest is `e5ef97c8087d679459f88af22761e9d048095bff1870ae414600617dcf0b41a8`.
