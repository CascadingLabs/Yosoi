"""Run with: uv run python examples/extractor_fields.py"""

# yosoi: allow-hardcoded-selectors -- this example documents deterministic extraction plans.
from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel
from typing_extensions import Self

import yosoi as ys

HTML = """
<main>
  <h1>Acme</h1>
  <meta name="industry" content="Manufacturing">
  <a href="https://linkedin.com/company/acme">LinkedIn</a>
  <a href="mailto:hello@acme.test">Email</a>
  <a href="tel:+15550100">Phone</a>
</main>
"""


class SocialProfile(BaseModel):
    platform: str
    url: str

    @classmethod
    def from_url(cls, url: str) -> Self | None:
        if 'linkedin.com/' in url:
            return cls(platform='linkedin', url=url)
        if 'x.com/' in url:
            return cls(platform='x', url=url)
        return None


class Company(ys.Contract):
    # No root: the complete document is one Company row.
    name: str = ys.css('h1').text()
    socials: list[SocialProfile] = ys.css('a[href]').attr('href').map(SocialProfile.from_url).compact()

    industry: str = ys.Extractor()

    @ys.extraction(industry)
    async def industry_from_meta(row: ys.ExtractionRow) -> str:
        values = row.attribute('meta[name="industry"]', 'content')
        if not values:
            raise ys.ExtractorNoMatch()
        return values[0]

    phone: str = ys.Extractor()
    emails: list[str] = ys.Extractor()

    @ys.extractions(phone, emails)
    async def contacts(row: ys.ExtractionRow) -> dict[str, object]:
        links = row.attribute('a[href]', 'href')
        phones = [value.removeprefix('tel:') for value in links if value.startswith('tel:')]
        if not phones:
            raise ys.ExtractorNoMatch('no phone')
        return ys.values(
            phone=phones[0],
            emails=[value.removeprefix('mailto:') for value in links if value.startswith('mailto:')],
        )


async def main() -> None:
    records = await ys.extract(HTML, Company, url='https://example.test/company/acme')
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
