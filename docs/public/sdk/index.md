---
title: SDK
description: Build Rust workflows with Yosoi.
order: 4
---

# SDK

Use `yosoi-sdk` as the public Rust facade. Operations share a Policy and return outcomes you can inspect.

## Modules

| Module              | Purpose                                  |
| ------------------- | ---------------------------------------- |
| Requests            | Fetch documents                          |
| Locate              | Select document values                   |
| [Map](map.md)       | Discover site URLs                       |
| [Search](search.md) | Find provider results                    |
| Policy              | Configure behavior and limits            |
| Contracts           | Describe and validate structured records |
| Archive             | Store and replay local captures          |

## Operation shape

Prepare an operation, bind a Policy, then send it. Inspect the outcome before passing data to the next operation.

The generated API reference will document the exact types and methods.
