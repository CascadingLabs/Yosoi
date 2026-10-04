# CAS-291: Capture Environment and Rendering Context Plan

Status: implemented design; canonical capture aggregation remains deferred to CAS-292/CAS-296

Linear: [CAS-291](https://linear.app/cascadinglabs/issue/CAS-291/define-capture-environment-and-rendering-context)

## Goal

Represent the environment that influenced a web capture without treating that environment as captured page content. The model must preserve the meaningful difference between native HTTP acquisition and browser rendering, make missing knowledge explicit, and prevent sensitive runtime configuration from leaking into ordinary capture metadata.

The design should support current browser contexts and future profile preparation strategies without making provider-specific mechanisms part of the stable capture shape.

## Design constraints

- Native HTTP captures must not invent viewport or browser-rendering values.
- Browser captures must state the context needed to interpret visual geometry.
- Known, unavailable, and intentionally omitted values must remain distinguishable.
- A VoidCrawl-controlled Chromium browser and a native HTTP client have different environment shapes.
- Provider and renderer identity matter, but provider names should not become top-level environment variants.
- Profile paths, cookies, credentials, OAuth state, request header values, and warm-up URLs may be necessary runtime inputs but must not appear in ordinary serialized environment metadata.
- Browser profile source, preparation, and retention are independent dimensions. In particular, a warmed profile can still be ephemeral.
- Canonical JSON and final capture identity rules belong to CAS-296. CAS-291 should define safe fingerprint inputs, not prematurely define canonical hashing.

## Boundary: request input versus captured environment

A browser acquisition request may need sensitive or machine-local inputs:

- a persistent profile path;
- an opaque managed-profile handle;
- cookie or credential access mediated by the provider;
- browser launch arguments;
- request headers;
- a future warm-up policy.

Those inputs are operational configuration. The finalized capture environment records only safe facts required to interpret or compare the result.

```text
Browser request                         Finalized capture environment
---------------                         -----------------------------
/home/user/.config/chrome-profile  ->   opaque profile identity, if allowed
cookies and OAuth tokens           ->   authenticated-state fact, if known
warm-up URLs and procedure          ->   preparation policy identity/version
raw launch arguments                ->   normalized effective rendering settings
raw request headers                 ->   typed representation-affecting facts
```

A runtime request type containing paths or secret handles should not implement `Serialize`. Secret-bearing values should be resolved only by the acquisition provider.

## Environment shape options

### Option A: semantic environment variants (recommended)

Use a closed top-level distinction between HTTP and browser environments. Provider and renderer identities are fields within the applicable variant.

```rust
pub enum CaptureEnvironment {
    Http(HttpCaptureEnvironment),
    Browser(BrowserCaptureEnvironment),
}

pub struct HttpCaptureEnvironment {
    pub client: Producer,
    pub user_agent: EnvironmentValue<UserAgent>,
    pub preferred_languages: EnvironmentValue<PreferredLanguages>,
}

pub struct BrowserCaptureEnvironment {
    pub controller: Producer,
    pub renderer: Producer,
    pub mode: EnvironmentValue<BrowserMode>,
    pub viewport: EnvironmentValue<Viewport>,
    pub device_scale_factor: EnvironmentValue<DeviceScaleFactor>,
    pub user_agent: EnvironmentValue<UserAgent>,
    pub locale: EnvironmentValue<Locale>,
    pub timezone: EnvironmentValue<TimeZone>,
    pub color_scheme: EnvironmentValue<ColorScheme>,
    pub reduced_motion: EnvironmentValue<ReducedMotion>,
}
```

Advantages:

- impossible to attach fictional viewport data to an HTTP environment;
- captures the stable semantic difference without coupling the wire model to VoidCrawl, Chrome DevTools Protocol, Firefox WebDriver, or a particular HTTP library;
- permits different controllers to use the same renderer;
- straightforward Serde representation and pattern matching.

Tradeoff:

- adding a fundamentally new acquisition family requires a schema revision and new enum variant.

### Option B: provider-specific top-level variants

```rust
pub enum CaptureEnvironment {
    NativeHttp(NativeHttpEnvironment),
    VoidCrawlChromium(VoidCrawlChromiumEnvironment),
    FirefoxWebDriver(FirefoxWebDriverEnvironment),
}
```

Advantages:

- every provider can expose its exact native shape;
- minimal translation from provider output.

Problems:

- provider upgrades become stable schema changes;
- equivalent Chromium environments controlled by different providers cannot be compared structurally;
- implementation identity and environment semantics become conflated;
- downstream consumers must understand every acquisition implementation.

This option is not recommended.

### Option C: universal property bag

```rust
pub struct CaptureEnvironment {
    pub kind: String,
    pub properties: Map<String, Value>,
}
```

Advantages:

- maximally extensible;
- providers can add fields without changing Rust types.

Problems:

- loses the static distinction motivating this ticket;
- permits browser-only data on HTTP captures;
- makes secrets and local paths easy to serialize accidentally;
- pushes validation and compatibility into every consumer.

This option should be explicitly rejected for ordinary environment metadata.

## Missing-information representation

Every optional observation should carry a state rather than use `Option<T>`:

```rust
pub enum EnvironmentValue<T> {
    Known(T),
    Unavailable { reason: ReasonCode },
    Omitted { reason: ReasonCode },
}
```

Meanings:

- `Known`: the effective value was observed or controlled.
- `Unavailable`: the producer could not determine the value.
- `Omitted`: the producer intentionally excluded it, normally because of policy or sensitivity.

The reason is a bounded, secret-safe `ReasonCode`, not a human message containing captured values.

This generic is justified because it enforces one shared state vocabulary across otherwise strongly typed fields. It should not become a generic metadata container.

## Browser geometry

A browser environment always contains explicit state for its viewport and device scale factor. The values need not always be known, but absence must be explained.

```rust
pub struct Viewport {
    width_css_pixels: NonZeroU32,
    height_css_pixels: NonZeroU32,
}

pub struct DeviceScaleFactor {
    // Representation to be selected before implementation.
}
```

Device scale factor options:

1. **Validated finite `f64`:** closest to browser APIs, but awkward for equality and later canonical serialization.
2. **Canonical positive decimal string:** preserves an exact provider-reported decimal and avoids floating-point serialization differences.
3. **Reduced positive rational:** exact and deterministic, but verbose and unlike browser APIs.

Recommendation: use a canonical positive decimal representation unless provider research shows that exact non-decimal floating-point values must be preserved. Do not silently round to a fixed number of decimal places.

## Future profile modeling (documented, not implemented)

Profile paths and managed-profile handles are important runtime request inputs, but profile management is explicitly outside CAS-291. The first environment schema therefore has no profile field at all. This keeps paths, cookies, credentials, warm-up URLs, and provider handles structurally outside ordinary environment metadata rather than attempting to redact them after serialization.

Future profile work should preserve one scaling rule: `ephemeral`, `persistent`, and `warmed` are not sibling variants. Source, preparation, and retention are orthogonal facts. A warmed profile can begin empty and still be discarded after one capture.

A future request model might separate those dimensions:

```rust
pub struct BrowserProfileRequest {
    pub source: ProfileSource,
    pub preparation: ProfilePreparation,
    pub retention: ProfileRetention,
}
```

A future finalized environment may retain only safe opaque identity and preparation-policy facts. It must never retain the runtime locator or preparation inputs. These types should be introduced only alongside a concrete profile consumer; CAS-291 records the design constraint without creating a speculative profile workflow language.

## Browser identity

Controller and renderer should remain separate concepts:

- controller example: VoidCrawl CDP driver;
- renderer example: Chromium with its actual implementation version.

The existing `Producer` and `ProducerVersion` types are candidates for both. Before implementation, verify whether their documented meaning is broad enough or whether a renderer-specific identity type is clearer.

Headless versus headful is a browser environment fact, not a capture target or separate acquisition family.

## Representation-affecting settings

Initial browser settings should stay narrow:

- viewport;
- device scale factor;
- user agent;
- locale;
- timezone;
- color scheme;
- reduced-motion preference;
- browser mode;
- renderer identity/version.

Potential future settings such as forced colors, contrast preference, touch capability, font configuration, and JavaScript policy should be added only when an acquisition provider can report or control them and an artifact consumer needs them.

Do not add an `extra` map for forward compatibility. Schema versioning should handle additions deliberately.

## Environment fingerprint options

### Option A: typed allowlisted fingerprint projection (recommended)

Expose or internally construct a projection containing only known representation-affecting facts and their semantic state. CAS-296 can later define canonical serialization and hashing.

```rust
pub struct EnvironmentFingerprintInputs<'a> {
    pub environment_kind: EnvironmentKind,
    pub implementation: &'a Producer,
    pub rendering_values: Vec<EnvironmentFingerprintValue<'a>>,
}
```

The production design need not use this exact generic/vector shape. The important property is an allowlist assembled from typed fields.

Advantages:

- auditable inputs;
- no dependence on incidental struct serialization;
- prevents runtime request configuration from entering the fingerprint.

### Option B: hash the entire serialized environment

Simple, but it prematurely couples fingerprint identity to Serde layout and CAS-296 canonicalization. It may also make safe metadata additions identity-breaking. Defer.

### Option C: hash everything except a denylist

This fails closed-schema and secrecy goals because new sensitive fields enter by default. Reject.

## Serialization direction

The checked-in desktop, mobile, and HTTP fixtures document the current ordinary Serde representation. They are review fixtures, not yet the canonical byte representation used for durable identity. CAS-296 owns that canonicalization contract.

## Proposed crate boundary

CAS-291 should eventually add environment domain types to `yosoi-web-capture`, likely in:

```text
crates/yosoi-web-capture/src/environment/mod.rs
crates/yosoi-web-capture/src/environment/{browser,fingerprint,http,value}.rs
crates/yosoi-web-capture/src/environment/scalars/*.rs
crates/yosoi-web-capture/tests/capture_environments.rs
crates/yosoi-web-capture/tests/fixtures/environment-desktop.json
crates/yosoi-web-capture/tests/fixtures/environment-mobile.json
crates/yosoi-web-capture/tests/fixtures/environment-http.json
```

CAS-295 owns target, origin, and request/acquisition modeling. The two tickets should compose later rather than defining one large request or capture aggregate now.

## Validation plan

- HTTP environment round-trips without browser-only fields.
- HTTP input containing viewport or profile context fails deserialization.
- Desktop and mobile-sized browser fixtures preserve geometry.
- Every environment observation state round-trips distinctly.
- Zero viewport dimensions and non-positive/non-finite scale factors fail construction.
- Unknown fields fail deserialization.
- No serializable environment type accepts a filesystem path, cookie collection, credential, arbitrary header map, arbitrary browser arguments, or arbitrary metadata map.
- Fingerprint inputs are built from an explicit allowlist.
- Future profile source, preparation, and retention remain documented as separate dimensions without speculative CAS-291 types.

## Decisions proposed for CAS-291

1. Use semantic `Http` and `Browser` environment variants.
2. Keep provider/controller and renderer identity as typed fields.
3. Use explicit `Known`, `Unavailable`, and `Omitted` states.
4. Keep runtime profile locators and secrets out of serialized capture metadata.
5. Keep profile context out of the first environment schema; document source, preparation, and retention as orthogonal concerns for future profile work.
6. Define allowlisted fingerprint inputs now; defer canonical hashing to CAS-296.
7. Do not implement warm-up behavior, profile management, storage, or acquisition in CAS-291.

## Open decisions before implementation

- Choose the exact device-scale-factor representation.
- Revisit safe profile identity only when concrete profile management is in scope.
- Confirm whether `Producer` is the right renderer identity type.
- Confirm which rendering preferences beyond color scheme belong in the first schema.
- Align any future profile request boundary with the settled CAS-295 browser-context references.
