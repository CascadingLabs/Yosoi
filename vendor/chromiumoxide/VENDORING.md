# Vendored Chromiumoxide fork

This fork was imported from `https://github.com/mattsse/chromiumoxide` at commit
`a7e2bb835b9643410f9e3dc044f0d947e96cbfa4`. Yosoi keeps it in-tree because the
VoidCrawl engine depends on reviewed controller changes that are not available
from the upstream crates.io release.

Preserve this commit identifier when updating or rebasing the fork so the
review boundary remains auditable.

## Local patch queue

The current local controller changes are intentionally kept separate from the
generated CDP schema:

1. bound the initial WebSocket connection by the configured launch timeout;
2. add normal and minimal CDP initialization modes;
3. omit eager Runtime, Network, Performance, Log, target-discovery,
   auto-attach, and utility-world setup in minimal mode;
4. synthesize explicitly created targets when global discovery is disabled;
5. allow callers to wait for an attached target's page initialization;
6. deduplicate target discovery so adopting a pre-existing page creates one
   CDP target session even when discovery events race `Target.getTargets`;
7. preserve browser-context identity and lower explicitly ignored invalid
   message logging to debug;
8. replace removed legacy `Network.InterceptionId` correlation with the active
   `Fetch.RequestId` identity required by the Chrome 153 protocol;
9. route stable `Target.targetCrashed` events to the matching owned page as a
   sticky page-scoped signal, without replacing normal browser event delivery;
   and
10. route normal-mode OOPIF frame events and frame-scoped commands through the
    owning flat session, initializing child Page/Runtime state before resuming
    it. Child-session Network adoption remains out of scope.

The controller still identifies as 0.9.1 at the upstream base above. Its CDP
dependency is the separately vendored `../chromiumoxide_cdp`, generated from
Chrome 153.0.8010.36 / Chromium revision `r1681091`.
