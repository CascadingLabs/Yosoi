# Vendored browser dependencies

These two directories work together:

- **`chromiumoxide`** controls the browser: connections, pages, navigation, and
  events. We keep a local fork for the browser-control fixes Yosoi needs.
- **`chromiumoxide_cdp`** defines the messages exchanged with Chrome through its
  DevTools Protocol. We keep generated Rust bindings for our selected Chrome
  version.

Keeping them separate lets us update protocol definitions independently of
browser-control fixes. Yosoi uses both through its internal VoidCrawl engine:

```text
Yosoi → VoidCrawl → chromiumoxide → chromiumoxide_cdp
```

See each directory's [controller vendoring notes](chromiumoxide/VENDORING.md)
and [protocol vendoring notes](chromiumoxide_cdp/VENDORING.md) for provenance
and maintenance details.
