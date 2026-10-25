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
- DOM-only Moli rejects input/PNG. Session viewport PNG does not certify Request
  visual artifacts/coordinates. AX, network/source bodies, layout artifacts and
  advanced watches remain explicitly unsupported.

The container is in `docker/moli`; permanent black-box tests are under
`python/tests/bidi` and the Rust test modules. Qualify native navigation, DOM,
input, frames, state, cancellation, disconnects, limits and cleanup with installed
Rust/Python consumers. Keep Chrome regressions green. A green gate does not
establish general graphics, performance, stealth or challenge-passage compatibility.
