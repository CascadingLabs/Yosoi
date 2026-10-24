---
title: 'Concepts'
description: 'Follow one eShop product from HTML bytes to validated data and dependable browser work.'
order: 0
---

# Concepts

This series follows the Arc desk lamp through [QScrape's eShop](https://qscrape.dev/eshop/). We start with a few HTML bytes, then introduce each capability when the task needs it.

The examples use Rust and Python with the same inputs and intended results wherever both interfaces support the task. Each language's explanation stays with its code. We assume Yosoi is already installed; [Install](../getting-started/install.md) covers that first step.

| Lesson                                                            | What changes in the task                                                  |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------- |
| [Making sense of HTML](documents-and-evidence.md)                 | Read product text and links from local bytes.                             |
| [Fetching our first page](discovery-and-acquisition.md)           | Obtain those bytes through HTTP.                                          |
| [Using a browser](using-a-browser.md)                             | Capture rendered evidence and choose headless or headful execution.       |
| [Waiting for the page](waiting-for-the-page.md)                   | Wait for the product before reading it.                                   |
| [Building a product record](contracts-and-validation.md)          | Validate typed records and inspect rejected candidates.                   |
| [Adding a product to the cart](adding-to-the-cart.md)             | Read controls, take an action, and check the resulting cart.              |
| [Following the data](following-the-data.md)                       | Work with JSON, XML, and plain text.                                      |
| [Building reusable browser recipes](actions-and-flows.md)         | Compose nested Flows, scripts, modules, and screenshots.                  |
| [Keeping the browser open](sessions-and-ownership.md)             | Share state across separate recipes.                                      |
| [Accessing a protected page](accessing-a-protected-page.md)       | Follow the site's verification workflow and retain unresolved outcomes.   |
| [Finding more pages](finding-more-pages.md)                       | Discover URLs with Map and Search.                                        |
| [Bounding the work](policy-and-budgets.md)                        | Handle limits, failed prerequisites, cancellation, and uncertain effects. |
| [Sharing browser capacity](sharing-browser-capacity.md)           | Separate tab authority from controller execution capacity.                |
| [Yielding while waiting](yielding-while-waiting.md)               | Let another tab use execution capacity while a wait retains control.      |
| [Keeping browser windows in Docker](browser-windows-in-docker.md) | Give a headful browser its own display and optional viewer.               |
| [Keeping the evidence](keeping-the-evidence.md)                   | Restore saved input and inspect retained automation records.              |
| [Exploring a surface](exploring-a-surface.md)                     | Read bounded structural views and drill into exact document evidence.     |
| [Exploring video evidence](exploring-video.md)                    | Navigate a frozen timeline and keep actual frames and crops.              |

Begin with [Making sense of HTML](documents-and-evidence.md).
