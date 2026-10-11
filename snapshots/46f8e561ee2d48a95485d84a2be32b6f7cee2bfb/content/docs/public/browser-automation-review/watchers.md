---
title: 'Observe without taking control'
description: '0.2.0 concept review. Rust examples describe the local spike; Python examples are proposals.'
order: 5
---

# Observe without taking control

A Watcher receives operation receipts from a Session. It does not acquire a
Work lease and cannot click, navigate or execute JavaScript.

## Two consumers see the same operation

With an open Session:

```rust
let mut first = session.watch();
let mut second = session.watch();
let work = session.work().await?;

let run = async {
    let navigation = work.navigate(url).await?;
    let first_copy = first.next().await?;
    let second_copy = second.next().await?;

    println!("{}", navigation.id);
    println!("{}", first_copy.id);
    println!("{}", second_copy.id);
    Ok::<_, yosoi::session::SessionError>(())
}.await;

first.close();
second.close();
let release = work.release().await;
let close = session.close().await;
run?;
release?;
close?;
```

Subscribe before triggering work so the first operation is included. For this
isolated example, all three IDs name the same operation. In a Session with more
activity, consumers need to correlate receipts by identity.

## What Watch does today

It provides bounded, Session-wide receipt fanout, including retained observations.
Slow consumers get an explicit lag error. One Watcher closing does not close
the others or stop Work. A receipt reports what was observed, rejected or unknown.

## What the original design wanted next

The broader sketches include approved network or visual subscriptions and
capture hooks around actions. Continuous raw network/AX streams and a hook such
as “screenshot 200 ms after click” are not delivered by the current Watch API.
Explicit collector subscriptions are a second-pass input.

## Decision to review

Are operation receipts and captures enough for 0.2.0, or is subscribing to
network/visual evidence around an action essential to your first real workflow?

**Recommendation:** define the required observation types before promising a
general event or callback system.
