---
title: 'Several async tasks, several tabs'
description: '0.2.0 concept review. Rust examples describe the local spike; Python examples are proposals.'
order: 3
---

# Several async tasks, several tabs

The spike coordinates tab ownership. Your application still chooses which
task runs on which tab.

## Two tabs with independent control

```rust
use yosoi::session::{self, SessionPolicy};

let session = session::new()
    .bind(&browser_policy)
    .configure(SessionPolicy {
        maximum_tabs: 2,
        ..SessionPolicy::default()
    })
    .acquire()
    .await?;

let second_tab = session.new_tab().await?;
let first_work = session.work().await?;
let second_work = second_tab.work().await?;

let (first, second) = tokio::join!(
    first_work.navigate(first_url),
    second_work.navigate(second_url),
);

let first_release = first_work.release().await;
let second_release = second_work.release().await;
let close = session.close().await;

first?;
second?;
first_release?;
second_release?;
close?;
```

This excerpt shows independent navigation and cleanup of held Work. A complete
application also needs to close the Session if setup fails partway through.

## Coordination already in the spike

Different tabs can make independent progress. Competing acquisitions of the
same tab wait within a bounded queue. Native clicks, text input and screenshots
share foreground ownership. A tab with an uncertain dispatched operation is
fenced against further use until cleanup.

The internal limits are 32 waiting Work acquisitions per tab, two browser-process
slots and 32 waiting Session acquisitions. These are safety bounds, not a
promise of throughput or support for every configured tab count.

## Still needs shaping

There is no public job scheduler assigning tabs, setting priorities or balancing
a fleet. Fairness, richer foreground coordination and local capacity/affinity
controls need review before we promise them.

Avoid holding tab A while indefinitely waiting to acquire tab B. A scheduler
needs a deliberate acquisition order or a way to release and try again.

## Decision to review

For 0.2.0, is explicit tab selection plus safe, bounded Work acquisition enough?
Or do you need a managed local queue that finds an available tab for each job?

**Recommendation:** release the explicit model first unless a concrete workflow
requires automatic assignment. Define contention, cancellation and foreground
behavior clearly either way.
