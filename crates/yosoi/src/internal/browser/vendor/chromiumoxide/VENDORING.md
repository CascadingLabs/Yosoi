# Private Chromiumoxide controller module

The upstream package is `chromiumoxide` 0.9.1, imported from
`https://github.com/mattsse/chromiumoxide` at commit
`a7e2bb835b9643410f9e3dc044f0d947e96cbfa4`. The former Yosoi fork package was
`yosoi-chromiumoxide` 0.9.1-yosoi.1. Its standalone Cargo manifest is removed;
this source now compiles as a private module in the `yosoi` SDK crate.

Yosoi keeps the controller in-tree because the browser adapter depends on
reviewed controller changes that are not available from the upstream release.
The original upstream authorship, README, and MIT/Apache license notices remain
alongside the source.

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
    it. Child-session Network adoption remains out of scope;
11. exclude service workers from page auto-attachment so their startup does
    not race debugger pause/resume and immediate detachment;
12. report child kill/reap failures during launch cleanup without panicking,
    preserving the original launch error.

The controller identity remains upstream version 0.9.1 at the base above. Its
private sibling module `../chromiumoxide_cdp` contains the generated bindings
from Chrome 153.0.8010.36 / Chromium revision `r1681091`.
