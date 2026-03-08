"""Type factories — parameterized parsing via the field-right pattern.

Demonstrates Yosoi's field-right type system:

    price: float = ys.Price(currency_symbol='€')
    url: str = ys.Url(strip_tracking=True)
    dt: str = ys.Datetime(past_only=True)
    rating: float = ys.Rating(as_float=True, scale=5)

  Plain Python type on the left, Yosoi factory on the right.
  100% mypy-compliant — no type: ignore needed.

  Contract.generate_manifest() — post-hoc introspection of all field configs

Run with:
    uv run python examples/type_factories.py
"""

import datetime as dt_module

from rich.console import Console
from rich.panel import Panel

import yosoi as ys
from yosoi.models.contract import Contract

console = Console()


# -- Contracts ----------------------------------------------------------------


class EuropeShop(Contract):
    """European e-commerce product — prices use EU comma-decimal format."""

    title: str = ys.Title()
    price: float = ys.Price(currency_symbol='€')
    url: str = ys.Url()
    rating: float = ys.Rating(as_float=True, scale=5)


class NewsArticle(Contract):
    """News article with robust datetime parsing and relative-URL resolution."""

    headline: str = ys.Title()
    author: str = ys.Author()
    published: str = ys.Datetime(past_only=True)
    url: str = ys.Url(strip_tracking=True)


class AffiliateProduct(Contract):
    """Product page where tracking params must be scrubbed from all links."""

    title: str = ys.Title()
    price: float = ys.Price()
    source_url: str = ys.Url(require_https=True, strip_tracking=True)
    discount_price: float | None = ys.Price()


# -- Demo helpers -------------------------------------------------------------


def section(title: str) -> None:
    console.print()
    console.print(Panel(f'[bold cyan]{title}[/bold cyan]', expand=False))


def show_row(label: str, before: object, after: object) -> None:
    console.print(f'  [dim]{label:<18}[/dim]  [yellow]{str(before)!r:<35}[/yellow]  ->  [green]{after!r}[/green]')


# -- Example 1: Price ---------------------------------------------------------


def demo_price() -> None:
    section('Price — EU/US heuristic + currency enforcement')

    cases = [
        ('EUR symbol', {'title': 'T', 'price': '€12.99', 'url': 'https://a.com', 'rating': '4'}),
        ('EU thousands', {'title': 'T', 'price': '1.200,50 €', 'url': 'https://a.com', 'rating': '5'}),
        ('EU bare comma', {'title': 'T', 'price': '49,99 €', 'url': 'https://a.com', 'rating': '3'}),
        ('Gratis', {'title': 'T', 'price': 'Gratis', 'url': 'https://a.com', 'rating': '1'}),
        ('Trailing text', {'title': 'T', 'price': '€9.99/mo', 'url': 'https://a.com', 'rating': '2'}),
    ]

    for label, raw in cases:
        result = EuropeShop.model_validate(raw)
        show_row(label, raw['price'], result.price)

    console.print()
    console.print('  [dim]Wrong currency symbol -> ValidationError:[/dim]')
    try:
        EuropeShop.model_validate({'title': 'T', 'price': '$9.99', 'url': 'https://a.com', 'rating': '4'})
    except Exception as e:
        msgs = [err['msg'] for err in e.errors()]  # type: ignore[attr-defined]
        console.print(f'  [red]  x {msgs[0]}[/red]')


# -- Example 2: Url -----------------------------------------------------------


def demo_url() -> None:
    section('Url — javascript blocked, tracking stripped, relative resolved')

    console.print('  [dim]javascript: href -> ValidationError:[/dim]')
    try:
        NewsArticle.model_validate(
            {
                'headline': 'H',
                'author': 'A',
                'published': '2026-01-01',
                'url': 'javascript:void(0)',
            }
        )
    except Exception as e:
        msgs = [err['msg'] for err in e.errors()]  # type: ignore[attr-defined]
        console.print(f'  [red]  x {msgs[0]}[/red]')

    dirty = 'https://example.com/article?utm_source=rss&utm_medium=email&id=99'
    result = NewsArticle.model_validate(
        {
            'headline': 'H',
            'author': 'A',
            'published': '2026-01-01',
            'url': dirty,
        }
    )
    show_row('tracking stripped', dirty, result.url)

    result2 = NewsArticle.model_validate(
        {'headline': 'H', 'author': 'A', 'published': '2026-01-01', 'url': '/story/123'},
        context={'source_url': 'https://news.example.com'},
    )
    show_row('relative -> absolute', '/story/123', result2.url)

    result3 = NewsArticle.model_validate(
        {
            'headline': 'H',
            'author': 'A',
            'published': '2026-01-01',
            'url': '//cdn.example.com/img.jpg',
        }
    )
    show_row('// -> https', '//cdn.example.com/img.jpg', result3.url)


# -- Example 3: Datetime ------------------------------------------------------


def demo_datetime() -> None:
    section('Datetime — dateparser-powered ISO 8601, editorial prefixes stripped')

    class AnyDate(Contract):
        dt: str = ys.Datetime()

    for raw in ['Updated: 2026-03-08T14:30:24Z', 'March 8th, 2026', 'Published: 2 days ago', '2026-01-15 09:00']:
        result = AnyDate.model_validate({'dt': raw})
        show_row('input', raw, result.dt)

    console.print()
    console.print('  [dim]Datetime(as_iso=False) -> datetime object:[/dim]')

    class ObjDate(Contract):
        dt: dt_module.datetime = ys.Datetime(as_iso=False)

    r = ObjDate.model_validate({'dt': '2026-06-01T12:00:00Z'})
    console.print(f'  [dim]type:[/dim] [green]{type(r.dt).__name__}[/green]  [dim]value:[/dim] [green]{r.dt}[/green]')
    assert isinstance(r.dt, dt_module.datetime)

    console.print()
    console.print('  [dim]Unparseable string -> ValidationError:[/dim]')
    try:
        AnyDate.model_validate({'dt': 'not a date xyz'})
    except Exception as e:
        msgs = [err['msg'] for err in e.errors()]  # type: ignore[attr-defined]
        console.print(f'  [red]  x {msgs[0]}[/red]')


# -- Example 4: Rating --------------------------------------------------------


def demo_rating() -> None:
    section('Rating — word mapping + numeric conversion')

    class Stars(Contract):
        rating: float = ys.Rating(as_float=True, scale=5)

    class RawStr(Contract):
        rating: str = ys.Rating()

    console.print('  [dim]Rating(as_float=True):[/dim]')
    for raw in ['Three', 'four stars', 'Five out of five', '4.5 / 5']:
        result = Stars.model_validate({'rating': raw})
        show_row('input', raw, result.rating)

    console.print()
    console.print('  [dim]ys.Rating() — raw string passthrough:[/dim]')
    r = RawStr.model_validate({'rating': 'Four stars out of five'})
    show_row('passthrough', 'Four stars out of five', r.rating)


# -- Example 5: generate_manifest() -------------------------------------------


def demo_manifest() -> None:
    section('Contract.generate_manifest() — field introspection')

    for contract_cls in (EuropeShop, NewsArticle, AffiliateProduct):
        manifest = contract_cls.generate_manifest()
        console.print(f'\n[bold]{contract_cls.__name__}[/bold]')
        for line in manifest.splitlines():
            if line.startswith('|'):
                console.print(f'  [dim]{line}[/dim]')


# -- Main ---------------------------------------------------------------------

if __name__ == '__main__':
    console.print(
        Panel(
            '[bold white]Yosoi Type System[/bold white]\n'
            '[dim]Plain Python types on the left, Yosoi factories on the right[/dim]',
            style='blue',
        )
    )

    demo_price()
    demo_url()
    demo_datetime()
    demo_rating()
    demo_manifest()

    console.print()
    console.print('[bold green]All demos complete[/bold green]')
