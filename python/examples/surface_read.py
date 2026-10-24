"""Acquire live HTML, inspect bounded evidence, and restore the same index."""

import argparse
import asyncio
import json

import yosoi as ys
from yosoi import surface as sf


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url", nargs="?", default="https://qscrape.dev/eshop/html/product/obj-001/"
    )
    parser.add_argument("query", nargs="?", default="lamp")
    parser.add_argument("archive", nargs="?", default="surface-evidence")
    args = parser.parse_args()
    response = await ys.request.new(args.url).send()
    if not response.documents:
        raise RuntimeError("acquisition returned no retained document")
    document = response.documents[0]
    index = sf.Surface(document)
    web = sf.WebSurface(index, args.url)
    result = web.read(sf.ReadRequest(operation=sf.Search(query=args.query)))
    archive = await ys.Archive.open(args.archive)
    reference = await archive.write(document)
    restored = sf.Surface(await archive.read(reference))
    print(
        json.dumps(
            {
                "descriptor": web.descriptor.model_dump(),
                "result": result.model_dump(),
                "archive_reference": reference.model_dump(),
                "same_observation": restored.metadata.identity
                == index.metadata.identity,
                "node_count": index.metadata.node_count,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
