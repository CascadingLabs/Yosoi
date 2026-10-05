"""Run real public-SDK operations to review authoring and typed outcomes."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

from pydantic import BaseModel

import yosoi as ys
from yosoi.errors import YosoiError, rust_error_details
from yosoi.policy import Documents, Map, Policy, ProviderSelection, Request, Search


def json_payload(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: json_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_payload(item) for item in value]
    return value


def show(label: str, value: object) -> None:
    print(f"\n--- {label} ---")
    if isinstance(value, BaseModel):
        print(value.model_dump_json(indent=2))
    else:
        print(json.dumps(json_payload(value), indent=2))


def policy_example() -> None:
    policy = Policy(
        request=Request(maximum_elapsed=10_000_000),  # Current Rust microsecond unit.
        documents=Documents(max_input_bytes=1_000_000, max_nodes=100_000),
    )
    restored = Policy.model_validate_json(policy.to_json())
    cloned = policy.clone()
    cloned.map.filters.excluded_query_keys.append("clone-only")
    show(
        "SDK clone keeps policy edits independent",
        {
            "original": policy.map.filters.excluded_query_keys,
            "clone": cloned.map.filters.excluded_query_keys,
        },
    )
    show("Authored policy with Rust defaults", json.loads(policy.to_json()))
    show("Resolved effective policy without I/O", policy.effective_policy())
    show("Immutable policy snapshot", policy.snapshot())
    deadline = ys.policy.MaximumElapsed.try_new(policy.request.maximum_elapsed)
    byte_limit = ys.policy.AddressableByteLimit.try_new(
        policy.documents.max_input_bytes
    )
    show(
        "Rust policy conversions with explicit units",
        {
            "deadline_microseconds": deadline.to_capture_deadline().as_microseconds(),
            "duration_microseconds": deadline.to_capture_deadline()
            .duration()
            .as_microseconds(),
            "input_byte_limit": byte_limit.to_byte_limit().get(),
        },
    )
    show(
        "Authored target before request preparation",
        ys.request.WebTarget.new("https://example.org/").as_str(),
    )
    show(
        "Saved and reloaded identities",
        {
            "original": policy.identity().model_dump(),
            "reloaded": restored.identity().model_dump(),
        },
    )
    bound = ys.request.new("https://example.org/").bind(policy)
    original = bound.policy.identity()
    policy.documents.max_nodes = 50_000
    show(
        "Editing a policy preserves an existing binding",
        {
            "binding_unchanged": bound.policy.identity() == original,
            "future_policy_changed": policy.identity() != original,
        },
    )


def errors_example() -> None:
    from yosoi.identities import ActivityId

    for action in (
        lambda: ys.css(""),
        lambda: ys.request.new("ftp://example.com").check(),
        lambda: ActivityId.from_str("invalid"),
        lambda: ys.Document.from_json("empty-json", b""),
        lambda: ys.Document.from_json("truncated-json", '{"title":').parse(),
    ):
        try:
            action()
        except YosoiError as error:
            detail = rust_error_details(error)
            show(
                "Actual Rust SDK error",
                {
                    "exception": type(error).__name__,
                    "message": str(error),
                    "rust_type": detail.rust_type if detail else None,
                    "variant": detail.variant if detail else None,
                    "details": dict(detail.details) if detail else None,
                },
            )
    show("Rust Map rejection Display", ys.map.rejection_message("host_scope"))
    show(
        "Rust Map declaration order",
        {
            "redirect_before_canonical": ys.map.compare_values(
                "relationship_kind", "redirect", "canonical"
            ),
            "seed_before_html_link": ys.map.compare_values(
                "discovery_source",
                ys.map.DiscoverySource(kind="seed"),
                ys.map.DiscoverySource(kind="html_link"),
            ),
        },
    )


def contracts_example() -> None:
    class Book(ys.Contract):
        """A book offered for sale."""

        root = ys.css("article")
        author: str = ys.Field("Author", id="byline", locator=ys.css(".author"))
        price: ys.Money = ys.Field("Price", locator=ys.css(".price"))
        tags: list[str] = ys.Field("Tags", locator=ys.css(".tag"))

    document = ys.Document.html(
        "books",
        """
        <article><b class=author>Ada</b><b class=price>$12.34</b>
            <i class=tag>computing</i></article>
        <article></article>
    """,
    )
    show("Pydantic record schema", Book.model_json_schema())
    show("Rust semantic schema", Book.contract_schema())
    show(
        "Rust Contract value IDs",
        {
            "str": ys.contracts.value_type_id(str),
            "Money": ys.Money.TYPE_ID,
        },
    )

    class SchemaScalar:
        TYPE_ID: ClassVar[str] = "review.scalar"

    show(
        "Custom schema identity (extraction supports str and Money)",
        ys.contracts.FieldSchema(
            id="review",
            description="A custom schema value identity",
            cardinality="exactly_one",
            value_type=ys.contracts.value_type_id(SchemaScalar),
        ),
    )
    show("Rust locator plan", Book.plan().compiled())
    extracted = ys.extract(document, Book)
    show("Rust extraction, including empty roots", extracted.model_dump())
    outcome = extracted.validate()
    show("Rust validation, including field issues", outcome.model_dump())
    show("Portable Rust Contract archive", outcome.to_archived().model_dump())
    for record in outcome.records:
        show("Named typed record", record.value)
        show("Candidate provenance", record.candidate)
    try:
        outcome.require_all()
    except ys.contracts.ContractIssues as error:
        show("Rust require_all rejection", error.detail)


def runtime_contracts_example() -> None:
    schema = ys.contracts.ContractSchema(
        id="books",
        description="Books from an external schema",
        scope="repeated",
        fields=(
            ys.contracts.FieldSchema(
                id="title",
                description="Title",
                cardinality="exactly_one",
                value_type="string",
            ),
        ),
    )
    contract = ys.contracts.RuntimeContract.new(schema)
    rows = ys.css("article").each_as_region(schema.id)
    plan = ys.Plan(outputs=[ys.output("title", rows.find(ys.css("h2")).text())])
    document = ys.Document.html("runtime-books", "<article><h2>Rust</h2></article>")
    extracted = contract.extract(document.locate(plan))
    show("Runtime extraction from public semantic schema", extracted.model_dump())
    outcome = extracted.validate()
    show("Runtime validation", outcome.model_dump())
    show("Portable archive from the runtime schema", outcome.to_archived().model_dump())
    for record in outcome.require_all():
        show("Typed runtime value and retained candidate", record)


def locate_example() -> None:
    document = ys.Document.html(
        "products",
        (
            '<article><h2>Tea</h2><a href="/tea">Details</a></article>'
            '<article><h2>Coffee</h2><a href="/coffee">Details</a></article>'
        ),
    )
    rows = ys.css("article").each_as_region("products")
    plan = ys.Plan(
        outputs=[
            ys.output("name", rows.find(ys.css("h2")).text()),
            ys.output("href", rows.find(ys.css("a")).attribute("href")),
        ]
    )
    show("Pydantic authoring plan", plan)
    show("Plan compiled by Rust", plan.compiled())
    outcome = document.locate(plan)
    show("Actual evidence and repeated-region lineage", outcome)
    with document.parse() as parsed:
        show(
            "Parse reuse",
            {
                "same_outcome": parsed.locate(plan) == outcome,
                "names": outcome.values("name"),
            },
        )
    show("Parsed handle closed", {"closed": parsed.closed})


async def request_example(url: str) -> None:
    request = ys.request.new(url).bind(Policy())
    request.check()
    response = await request.send()
    show("Actual request outcome", response)
    plan = ys.Plan(outputs=[ys.output("heading", ys.css("h1").text())])
    for attempt in response.attempts:
        for item in attempt.documents:
            if item.outcome.document is not None:
                show("Locate the retained document", item.outcome.document.locate(plan))


async def map_example(seed: str) -> None:
    policy = Policy(map=Map(documents="retain_within_budget"))
    policy.map.limits.max_requests = 4
    policy.map.limits.max_link_depth = 0
    policy.map.limits.max_concurrency = 1
    request = ys.map.new(seed).bind(policy)
    request.check()
    show("Actual bounded discovery outcome", await request.send())


async def search_example(query: str, provider: str) -> None:
    selection = ProviderSelection.model_validate({"provider": provider})
    policy = Policy(search=Search(providers=[selection]))
    policy.search.max_in_flight = 1
    request = ys.search.new(query).bind(policy)
    request.check()
    show(
        "Actual provider outcome, including unavailable/failure states",
        await request.send(),
    )


async def cancellation_example(url: str) -> None:
    token = ys.CancellationToken()
    token.cancel()
    response = await ys.request.new(url).send(cancellation=token)
    show("Explicit cancellation before I/O", response)


async def local_example() -> None:
    class Site(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/robots.txt":
                body, status, media = b"User-agent: *\nAllow: /\n", 200, "text/plain"
            elif self.path == "/sitemap.xml":
                body, status, media = b"", 404, "application/xml"
            else:
                body = b'<html><h1>Live local SDK</h1><a href="/next">Next</a></html>'
                status, media = 200, "text/html; charset=utf-8"
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Site)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        await request_example(url)
        await map_example(url)
        await cancellation_example(url)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "policy",
        "errors",
        "locate",
        "contracts",
        "runtime-contracts",
        "local",
    ):
        commands.add_parser(name)
    for name in ("request", "map", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("url", nargs="?", default="https://example.org/")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument(
        "--provider", choices=["brave", "bing", "duck_duck_go"], default="bing"
    )
    args = parser.parse_args()
    show(
        "Interpreter and SDK",
        {
            "yosoi": ys.__version__,
            "python": sys.version,
            "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
        },
    )
    try:
        if args.command == "policy":
            policy_example()
        elif args.command == "errors":
            errors_example()
        elif args.command == "runtime-contracts":
            runtime_contracts_example()
        elif args.command == "contracts":
            contracts_example()
        elif args.command == "locate":
            locate_example()
        elif args.command == "local":
            asyncio.run(asyncio.wait_for(local_example(), 45))
        elif args.command == "search":
            asyncio.run(asyncio.wait_for(search_example(args.query, args.provider), 45))
        else:
            operation = {
                "request": request_example,
                "map": map_example,
                "cancel": cancellation_example,
            }[args.command]
            asyncio.run(asyncio.wait_for(operation(args.url), 45))
    except Exception as error:
        show(
            "Operation could not complete",
            {
                "exception": type(error).__name__,
                "message": str(error),
            },
        )
        return 1
    show(
        "Interpreter after SDK operations",
        {
            "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
