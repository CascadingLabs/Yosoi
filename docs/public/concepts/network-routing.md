---
title: Choosing a network route
description: Opt into IPv4 or IPv6 connections, local source binding, and URL-configured proxies.
order: 16
---

# Choosing a network route

Set `Policy.network` before sending a Request or acquiring a Session. The default keeps existing networking behavior. An explicit network policy owns its route for the operation's lifetime, including Direct HTTP redirects and browser web requests.

## Example: choose IPv6

These programs request the same product page through IPv6. They require a working IPv6 route to the site. Use `Ipv4Only` in Rust or `"ipv4_only"` in Python to select IPv4 instead. A missing route produces a failed acquisition instead of retrying over the other family.

### Rust

```rust
use std::error::Error;
use yosoi::{policy::{IpFamily, Network, Policy}, request};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv6Only,
            ..Network::default()
        },
        ..Policy::default()
    };
    let response = request::new("https://qscrape.dev/eshop/html/product/obj-001/")
        .bind(&policy)
        .send()
        .await?;
    for attempt in response.attempts() {
        println!("{:?}: {:?}", attempt.state(), attempt.status());
    }
    Ok(())
}
```

Inspect the attempt state and HTTP status. A completed acquisition can still contain an HTTP error or incomplete document evidence.

### Python

```python
import asyncio
from yosoi import request
from yosoi.policy import Network, Policy


async def main() -> None:
    policy = Policy(network=Network(ip_family="ipv6_only"))
    response = await request.new(
        "https://qscrape.dev/eshop/html/product/obj-001/"
    ).bind(policy).send()
    for attempt in response.attempts:
        print(attempt.state, attempt.http_status)


asyncio.run(main())
```

The Python declaration is validated by Rust. Inspect the attempt state and HTTP status before using the captured documents.

## Bind a local source address

`source_address` selects an IP already assigned to the machine. It does not allocate an address or choose the public IP after NAT. For example, set Rust's `policy.network.source_address = Some("::1".parse()?);` or Python's `policy.network.source_address = "::1"` when contacting a local IPv6 fixture. Family and source must agree. Use `None` to let the operating system choose an address. Wildcard and multicast values are rejected; an unavailable concrete address fails when the socket binds.

## Example: use an upstream proxy

Read the proxy URL from the environment so it stays out of source code. These complete programs expect `YOSOI_PROXY_URL`, such as `http://proxy.example:8080` or `socks5h://user:password@proxy.example:1080`. Percent-encode special characters in credentials.

### Rust

```rust
use std::{env, error::Error};
use yosoi::{policy::{Network, Policy}, request};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = Policy {
        network: Network {
            proxy: Some(env::var("YOSOI_PROXY_URL")?),
            ..Network::default()
        },
        ..Policy::default()
    };
    let response = request::new("https://qscrape.dev/eshop/html/product/obj-001/")
        .bind(&policy)
        .send()
        .await?;
    for attempt in response.attempts() {
        println!("{:?}", attempt.state());
    }
    Ok(())
}
```

The request owns the local tunnel until its response body settles. Destination TLS remains between the HTTP client and site.

### Python

```python
import asyncio
import os
from yosoi import request
from yosoi.policy import Network, Policy


async def main() -> None:
    policy = Policy(network=Network(proxy=os.environ["YOSOI_PROXY_URL"]))
    response = await request.new(
        "https://qscrape.dev/eshop/html/product/obj-001/"
    ).bind(policy).send()
    print([attempt.state for attempt in response.attempts])


asyncio.run(main())
```

The native request owns and closes the tunnel. Python does not need to manage a second proxy process.

## Proxy URL behavior

| Scheme    | Connection to proxy            | Destination lookup | Authentication                |
| --------- | ------------------------------ | ------------------ | ----------------------------- |
| `http`    | Plain TCP, default port 80     | Upstream proxy     | Optional Basic user/password  |
| `https`   | Verified TLS, default port 443 | Upstream proxy     | Optional Basic user/password  |
| `socks5`  | Plain TCP, default port 1080   | Local resolver     | Optional SOCKS5 user/password |
| `socks5h` | Plain TCP, default port 1080   | Upstream proxy     | Optional SOCKS5 user/password |

HTTP proxies must support CONNECT to the destination port, including port 80 for plain HTTP sites. Proxy URLs cannot contain a path, query, or fragment. Unsupported schemes and malformed URLs fail validation. Proxy rejection never falls back to a direct connection. An explicit family or source policy with no proxy connects directly; ambient proxy environment settings are not merged into that policy.

With an upstream proxy, `ip_family` and `source_address` apply to the connection **to the proxy**. The proxy controls its own destination connection. Selecting IPv6 here does not promise that the site observes IPv6. The helper uses a loopback connection in the selected family. Local DNS lookups use the operating system's resolver configuration.

Proxy passwords are redacted from Rust Debug and Python repr output. They remain in serialized policies and archived snapshots, so protect those artifacts as credentials.

## Example: retain the route in a Session

The Session owns its tunnel, and every tab shares the acquired route. These programs need the [browser feature and a supported regular Chrome installation](../sdk/browser.md).

### Rust

```rust
use std::error::Error;
use yosoi::{policy::{Acquisition, BrowserMode, IpFamily, Network, Policy}, request, session};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv4Only,
            ..Network::default()
        },
        ..Policy::default()
    };
    policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless)];
    let session = session::new().bind(&policy).acquire().await?;
    let result = request::new("https://qscrape.dev/eshop/html/product/obj-001/")
        .in_session(&session)
        .send()
        .await;
    session.close().await?;
    println!("{:?}", result?.termination());
    Ok(())
}
```

Close the Session even when the request fails. Requests and Flows bound to this Session inherit its networking policy; binding a different route returns an error.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.policy import Acquisition, Network, Page, Policy


async def main() -> None:
    policy = Policy(
        network=Network(ip_family="ipv4_only"),
        page=Page(acquisitions=[Acquisition.browser()]),
    )
    async with ys.session(policy=policy) as session:
        response = await ys.request.new(
            "https://qscrape.dev/eshop/html/product/obj-001/"
        ).in_session(session).send()
        print([attempt.state for attempt in response.attempts])


asyncio.run(main())
```

The context closes both browser ownership and the local tunnel. Changing the original policy does not change an already acquired Session's route.

## Coverage and limits

Chrome and owned Firefox or Moli sessions send their TCP web requests through the same local relay. This includes HTTP, HTTPS, WebSockets, redirects, subresources, frames, and worker web requests supported by the selected engine. Native BiDi engines attach the SOCKS route to each created user context. Firefox explicitly makes localhost honor it; Moli's scoped proxy also routes localhost. Moli 1.1.19 does not expose a service-worker runtime. Chrome disables its implicit localhost bypass, QUIC, and non-proxied WebRTC UDP. Routing does not relax browser sandbox or site-isolation settings. There is no direct fallback for the selected TCP route. Remote Firefox and Moli endpoints reject custom routing before browser admission.

The local helper is an in-process TCP tunnel with at most 64 active connections and a 30-second handshake bound. Request deadlines, Session startup cancellation, and owner cleanup still apply. It does not intercept destination TLS, provide a UDP proxy, replace an operating-system firewall, or guarantee that every browser subsystem and DNS packet uses the selected route. Stronger process-wide network isolation requires an external operating-system boundary.
