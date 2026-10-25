"""Send a Python SDK Request through an explicitly selected network policy."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import yosoi as ys
from yosoi.policy import Acquisition, Network, Page, Policy


async def run(args: argparse.Namespace) -> int:
    """Bind one route, send the request, and close any owned browser Session."""
    proxy = os.environ[args.proxy_env] if args.proxy_env else None
    policy = Policy(
        network=Network(
            ip_family=args.ip_family,
            source_address=args.source_address,
            proxy=proxy,
        )
    )
    if args.browser:
        policy.page = Page(acquisitions=[Acquisition.browser()])
        async with ys.session(policy=policy) as session:
            response = await ys.request.new(args.url).in_session(session).send()
    else:
        response = await ys.request.new(args.url).bind(policy).send()

    print(
        json.dumps(
            {
                "ip_family": policy.network.ip_family,
                "proxy_configured": proxy is not None,
                "attempts": [
                    {
                        "state": attempt.state,
                        "http_status": attempt.http_status,
                        "documents": [
                            document.outcome.status for document in attempt.documents
                        ],
                    }
                    for attempt in response.attempts
                ],
            },
            indent=2,
        )
    )
    return 0 if all(a.state == "completed" for a in response.attempts) else 1


def main() -> int:
    """Select an IP family, optional source/proxy, and HTTP or browser acquisition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument(
        "--ip-family",
        choices=["system_default", "ipv4_only", "ipv6_only"],
        default="system_default",
    )
    parser.add_argument("--source-address")
    parser.add_argument(
        "--proxy-env",
        nargs="?",
        const="YOSOI_PROXY_URL",
        help="Read the proxy URL from this environment variable (YOSOI_PROXY_URL).",
    )
    parser.add_argument("--browser", action="store_true")
    return asyncio.run(asyncio.wait_for(run(parser.parse_args()), 30))


if __name__ == "__main__":
    raise SystemExit(main())
