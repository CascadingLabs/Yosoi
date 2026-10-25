# Native WebDriver BiDi

Private implementation for regular Firefox and pinned Moli. `browser-bidi`
enables execution; configuration/Archive inspection does not need that feature
or installed browser binaries. Chrome/CDP stays behind its existing adapter.

- Session owns lifecycle; Work owns exclusive tab control. Raw protocol handles
  stay private. Engine, protocol, mode, profile and executable identity are distinct.
- The transport actor bounds messages, commands and events, correlates checked
  JSON-safe IDs, retains early events and reports overflow. Cancellation after
  enqueue fences the connection; late replies cannot complete another operation.
- Cleanup owns only explicitly created contexts. A remote endpoint does not grant
  process ownership or attest identity/egress policy. Uncertain cleanup stays uncertain.
- Contexts, frames and realms are distinct. Native input revalidates the current
  target, geometry and trusted effects. Moli's viewport adapter requires layout
  and Screenshot permission; standard element-origin rejection is a negative test.
- No JavaScript activation, silent CDP fallback or replay of uncertain mutations.
  Script capability never grants arbitrary-script permission.
- DOM-only Moli rejects input/PNG. Desktop viewport/DPR, locale and timezone
  overrides use native scoped commands; mobile/touch device identities reject
  before mutation. Both layout engines have native viewport/full-page/cropped
  PNG metadata bound to the same document epoch, including DPR and scrollbars.
  Firefox also exposes CSSOM layout metrics. Moli layout-only capture cannot
  silently spend Screenshot permission to refresh its renderer.
- Firefox network subscriptions and response collectors feed the shared bounded
  navigation report. Collector byte limits concern encoded items; local retained
  limits concern decoded bytes, and the transport bounds materialization. Bodies
  absent from the remote collector remain unavailable, never DOM replacements.
  Firefox's text-MIME conversion can alter non-UTF-8 bytes before returning them
  through BiDi. Require its completed response's decoded byte extent to match
  the retrieved body; mismatches or missing extents remain unavailable. Do not
  guess an inverse charset conversion or serialize altered bytes as HTTP source.
  The pinned release can report decoded size zero for nonempty bodies. Encoded
  `bodySize` establishes decoded extent only for uncompressed responses; a
  compressed response without a usable decoded extent stays unavailable.
- Pinned Moli 1.1.19 omits top-level document network events and source bodies
  in isolated user contexts. Fetch/subresource events and collected bodies work,
  including collector isolation across two user contexts. Its network graph is
  always marked incomplete, and its events cannot prove network quiet. Do not
  fabricate the missing document from DOM or use the shared default context.
  Global/scoped subscriptions, command order and document priming did not repair
  this limit; requalify it when changing the pinned engine.
- Moli's active-navigation reply ID can differ from its lifecycle event ID after
  Fetch. Reject active-navigation tracking rather than correlate by URL alone.
  Its DOM-ready command path remains supported. A pre-commit script cannot stop
  its pending navigation reliably; cancellation remains explicitly uncertain.
- DOM and selected-response watches use native channels and context-scoped body
  collectors. Candidate ownership includes the watch, frame and document epoch;
  native scopes explicitly omit CDP loader IDs. Repeated body reads preserve the
  collector until acknowledged teardown. Native log subscriptions retain console
  and exception text under the shared UTF-8 budget; null text is unknown loss,
  not an empty message. Moli does not report tested uncaught timer exceptions,
  so its exception coverage remains incomplete.
- Full browser AX trees and AX change watches remain unsupported. Accessibility
  locators are native role/name queries, not a full-tree export. DOM-derived
  semantics must never be labeled Chromium AX evidence.

The container is in `docker/moli`; permanent black-box tests are under
`python/tests/bidi` and the Rust test modules. Qualify native navigation, DOM,
input, frames, state, cancellation, disconnects, limits and cleanup with installed
Rust/Python consumers. Keep Chrome regressions green. A green gate does not
establish general graphics, performance, stealth or challenge-passage compatibility.

## Controller parity inventory

This inventory covers the provider boundary in `controller.rs`, rather than every
command offered by CDP. Shared types do not establish equivalent engine support.

| Controller operations | Firefox 158.0.1 | Moli 1.1.19 |
| --- | --- | --- |
| Launch/close, isolated contexts, additional pages | Native | Native |
| Managed profile, custom proxy routing | Unsupported | Unsupported |
| Navigate, DOM-ready navigation, document scope/URL | Native | Native |
| Active-navigation progress/cancellation | Native | Rejected: unreliable navigation IDs |
| Stop loading | Native utility | Acknowledged document only; uncommitted navigation rejected |
| DOM snapshot, frame enumeration, main/frame scripts | Native | Native |
| Trusted click/type, scoped input | Main-document targets | Main-document targets, layout and Screenshot permission |
| Condition waits, DOM and response watches | Native | Native |
| Navigation network/source capture | Native collectors | Fetch/subresources only; graph incomplete |
| Selected response-body capture and repeated reads | Native collectors | Native collectors |
| Runtime console/exception capture | Native logs | Console; uncaught-exception coverage incomplete |
| Layout metrics | CSSOM, with provenance | Standalone rejected: requires raster refresh |
| Viewport/full-page/explicit-box visual capture | Native PNG | Native PNG, layout profile |
| Visual selector/temporary viewport/scroll options | Not implemented | Not implemented |
| Desktop viewport/DPR, locale, timezone | Native commands | Native commands |
| Mobile/touch/device identity | Unsupported | Unsupported |
| Rendering preferences | Command wired; qualified release rejects it | Command wired; not qualified |
| Full AX tree and AX-change watches | No native tree export | No native tree export |

`visual_snapshot` returns bytes on both providers; filesystem paths are not part
of that operation's contract. Chrome-specific instrumentation flags remain false
on BiDi even when equivalent native collectors are active. Unknown cache and
service-worker provenance remains unknown. Remote-service process identity and
egress are operator-owned facts, not inferred from a Chrome-like user agent.
