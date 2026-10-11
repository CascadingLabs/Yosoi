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
    preserving the original launch error;
13. allow `Runtime.awaitPromise` to use an explicit finite controller deadline
    through both the command future and handler response accounting. Ordinary
    commands retain their configured timeout. This local-only metadata never
    enters the CDP wire request, and expired futures fail before dispatch;
14. replace the page-side `IntersectionObserver` wait used by element scrolling
    with the existing `DOM.scrollIntoViewIfNeeded` command and its
    `RemoteObjectId`. Keep the subsequent clickable-point and native input path
    unchanged. This avoids depending on a renderer callback to finish scrolling
    an inactive headful tab. Puppeteer's CDP element implementation uses the
    same command/object identity in [`CdpElementHandle.scrollIntoView`](https://raw.githubusercontent.com/puppeteer/puppeteer/main/packages/puppeteer-core/src/cdp/ElementHandle.ts#L81-L93);
15. expose the existing main-world globally unique execution-context ID
    alongside its owning flat session, and use the Runtime evaluation/function
    call `uniqueContextId` parameters
    for scope-bound Until JavaScript. This avoids numeric execution-context ID
    reuse across renderer processes and rejects a missing, swapped, or
    out-of-scope context instead of evaluating in a replacement realm. The
    pinned M153 bindings already expose this parameter, so no schema change is
    needed.

Patch 13 supports acknowledged DOM observers parked outside SDK worker capacity.
Without it, the command future's independent 30-second timer can cut short a
longer configured action/condition wait. The SDK retains its original absolute
action deadline and cancellation scope; observer cleanup remains bounded.
The focused command-future regression and live wait beyond 30 seconds belong
to CAS-571's validation rather than a protocol-version or browser promotion.

Patch 14 addresses a headful multi-tab fixture that timed out before its
trigger request, with zero Until evaluations. The observed path is consistent
with waiting on the renderer-side intersection observer while the clicked tab
is in the background. CDP scrolling removes that callback dependency; native
input also needs the provider's guarded foreground preparation for a hidden
headful tab. A focused background-tab case passed after the provider change.
The recorded full headful run on later scope changes passed 15 of 16 cases; its
background typing fixture completed the step but did not produce the expected
typed value. An earlier full headful pass predates those scope changes. These
are capability results for the recorded regular Chrome runtime, not a full
browser promotion.

Patch 15's scope-bound Until evaluation preserves Chromiumoxide's existing
`Evaluation::from(&str)` function-versus-expression detection. Expressions use
`Runtime.evaluate` with `uniqueContextId`; function and arrow strings use
`Runtime.callFunctionOn` with the same globally unique context and the expected
frame session. Neither path falls back to a numeric context ID or a replacement
realm. The provider's scoped input path likewise keeps the resolved element
handle and verifies its document scope before native input. The focused scope
fixtures passed in headless and headful modes; the latest full headful typing
failure remains open.

The controller identity remains upstream version 0.9.1 at the base above. Its
private sibling module `../chromiumoxide_cdp` contains the generated bindings
from Chrome 153.0.8010.36 / Chromium revision `r1681091`.
