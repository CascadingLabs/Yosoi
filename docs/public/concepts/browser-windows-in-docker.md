---
title: 'Keeping browser windows in Docker'
description: 'Give a headful browser its own virtual display instead of opening windows on your desktop.'
order: 15
---

# Keeping browser windows in Docker

You've seen headful browser windows pop up over your desktop. What if they stayed out of the way? A Docker container can give the browser its own display, with a viewer you open only when you want to watch.

Headful still means the browser has a window. The difference is where that window lives. Inside the headful image, Sway supplies a virtual Wayland display. Your desktop does not host that window, and the browser does not become headless simply because you aren't looking at it.

## Give the browser its own environment

A container packages the browser and its operating-system dependencies. The headful image adds the display and viewer; the headless image omits them. Neither mode makes a verification workflow succeed automatically or establishes the cost of a large scraping job.

For the installation commands and requirements, see [Docker setup](../getting-started/docker.md). Start its headful container and wait for its health status to become `healthy` before running this example.

## Example: open the lamp inside the container

These commands use the headful container named `yosoi-browser` from Docker setup. They create a browser tab for the same static lamp page we used earlier, then open its display viewer.

```sh
docker exec yosoi-browser curl -fsS -X PUT \
  'http://127.0.0.1:19222/json/new?https://qscrape.dev/eshop/html/product/obj-001/'

docker exec yosoi-browser viewerctl open --browser 1 --ttl 15m
```

The first command talks to Chrome's local debugging endpoint. It returns information about the new tab, including its URL and target ID; page loading can continue after that response. The second prints a temporary viewer URL. Open that URL to see the lamp page on the container's display once it loads.

This is a browser-service example, so the commands are the same whether your application uses Rust or Python. It does not run a Yosoi Flow or validate the product. It shows where the browser window goes.

## A display is different from a connection

CDP, the Chrome DevTools Protocol, lets an automation client control an existing browser. The service exposes that interface on container loopback. Having a CDP endpoint does not mean the current Yosoi Session API can attach to it.

Today, a Yosoi Session starts a locally managed browser; its remote-endpoint setting is unsupported. Starting this container therefore does not move your earlier Rust or Python program into it. Moving the application too requires an application image containing the SDK and its runtime, alongside a compatible browser and the display it needs. The browser-service images here do not include that application.

The container's lifetime and the application's Session lifetime also remain separate. A viewer is another way to control the displayed browser, so its actions can change state that an automation client is observing.

## Watch only when needed

You can leave the headful display running without keeping its viewer open. Closing the viewer removes your access to the display; it does not switch the browser to headless mode or stop it.

```sh
docker exec yosoi-browser viewerctl close
```

When you're finished with the browser itself:

```sh
docker stop yosoi-browser
```

The container is removed because Docker setup started it with `--rm`. Its temporary profiles disappear with it. Retain the Documents and receipts your application needs before ending the environment that produced them.

## Next

[Keeping the evidence](keeping-the-evidence.md) preserves those inputs and observations after browser work ends.
