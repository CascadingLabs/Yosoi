"""Custom type — extending Yosoi with your own semantic type.

Demonstrates both patterns for defining a custom type:

  1. @register_coercion  (preferred — one function, zero boilerplate)
  2. class MyType(YosoiType)  (OOP style, groups coerce + factory under one name)

After definition, custom types work exactly like built-ins:

    phone: str = PhoneNumber(country_code='+44')
    isbn: str = ISBN.field(require_isbn13=True)

Run with:
    uv run python examples/custom_type.py
"""

import re
from typing import Any

from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.types.registry import register_coercion

console = Console()


# =============================================================================
# Pattern 1: @register_coercion  (preferred)
# =============================================================================
#
# The decorator does two things at once:
#   - stores the function body in the registry as the coerce logic
#   - replaces the name with a Field factory whose kwargs match the config
#
# Decorator kwargs become the config schema:
#   description  -> default Field description
#   country_code -> goes into json_schema_extra, becomes a factory param
#
# Result: PhoneNumber is now a Field factory.
# PhoneNumber()              -> Field(json_schema_extra={'yosoi_type': 'phone', 'country_code': '+1'})
# PhoneNumber(country_code='+44') -> Field(json_schema_extra={..., 'country_code': '+44'})


@register_coercion('phone', description='A phone number', country_code='+1')
def PhoneNumber(v: object, config: dict[str, Any], source_url: str | None = None) -> str:
    """A phone number field — strips formatting and prepends a country code."""
    raw = str(v).strip()
    digits = re.sub(r'\D', '', raw)
    if not digits:
        raise ValueError(f'No digits found in phone value: {v!r}')
    cc = config.get('country_code', '+1')
    cc_digits = re.sub(r'\D', '', cc)
    if digits.startswith(cc_digits):
        return f'+{digits}'
    return f'{cc}{digits}'


# =============================================================================
# Pattern 2: class MyType(YosoiType)
# =============================================================================
#
# Useful when you prefer OOP or want the coerce logic and field factory
# grouped under one class name.  __init_subclass__ handles registration.
# You write the Field factory yourself as a classmethod.


class ISBN(ys.YosoiType):
    """An ISBN-10 or ISBN-13 field that normalises to digits-only."""

    type_name = 'isbn'

    @staticmethod
    def coerce(v: object, config: dict[str, Any], source_url: str | None = None) -> str:  # noqa: ARG004
        """Strip hyphens/spaces and optionally enforce ISBN-13 length."""
        raw = re.sub(r'[\s\-]', '', str(v))
        if not raw.isdigit():
            raise ValueError(f'ISBN contains non-digit characters after normalisation: {raw!r}')
        require_isbn13: bool = config.get('require_isbn13', False)
        if require_isbn13 and len(raw) != 13:
            raise ValueError(f'Expected ISBN-13 (13 digits), got {len(raw)}: {raw!r}')
        return raw

    @classmethod
    def field(
        cls,
        require_isbn13: bool = False,
        description: str = 'An ISBN-10 or ISBN-13 identifier',
        **kwargs: Any,
    ) -> Any:
        """Build a pydantic FieldInfo for this type.

        Example::

            class BookListing(Contract):
                isbn: str = ISBN.field()
                isbn13: str = ISBN.field(require_isbn13=True)
        """
        from yosoi.types.field import Field

        return Field(
            description=description,
            json_schema_extra={'yosoi_type': cls.type_name, 'require_isbn13': require_isbn13},
            **kwargs,
        )


# =============================================================================
# Contracts using the custom types — identical to built-in usage
# =============================================================================


class ContactPage(Contract):
    """Contact details scraped from a business directory."""

    name: str = ys.Title()
    us_phone: str = PhoneNumber()
    uk_phone: str = PhoneNumber(country_code='+44')
    website: str = ys.Url()


class BookListing(Contract):
    """Book record with ISBN normalisation."""

    title: str = ys.Title()
    author: str = ys.Author()
    price: float = ys.Price()
    isbn: str = ISBN.field()
    isbn13: str = ISBN.field(require_isbn13=True)


# =============================================================================
# Demo
# =============================================================================


def section(title: str) -> None:
    console.print()
    console.print(Panel(f'[bold cyan]{title}[/bold cyan]', expand=False))


def show_row(label: str, before: object, after: object) -> None:
    console.print(f'  [dim]{label:<22}[/dim]  [yellow]{str(before)!r:<35}[/yellow]  ->  [green]{after!r}[/green]')


def demo_phone() -> None:
    section('PhoneNumber — @register_coercion')

    cases = [
        (
            'US with dashes',
            {'name': 'Acme', 'us_phone': '555-867-5309', 'uk_phone': '+44 20 7946 0958', 'website': 'https://acme.com'},
        ),
        (
            'US parentheses',
            {
                'name': 'Acme',
                'us_phone': '(555) 867 5309',
                'uk_phone': '+44 20 7946 0958',
                'website': 'https://acme.com',
            },
        ),
        (
            'UK spaces',
            {'name': 'Acme', 'us_phone': '5558675309', 'uk_phone': '020 7946 0958', 'website': 'https://acme.com'},
        ),
    ]

    for label, raw in cases:
        result = ContactPage.model_validate(raw)
        show_row(f'{label} (US)', raw['us_phone'], result.us_phone)
        show_row(f'{label} (UK)', raw['uk_phone'], result.uk_phone)

    console.print()
    console.print('  [dim]No digits -> ValidationError:[/dim]')
    try:
        ContactPage.model_validate(
            {'name': 'X', 'us_phone': 'N/A', 'uk_phone': '+44 20 7946 0958', 'website': 'https://x.com'}
        )
    except ValidationError as e:
        msgs = [err['msg'] for err in e.errors()]
        console.print(f'  [red]  x {msgs[0]}[/red]')


def demo_isbn() -> None:
    section('ISBN — YosoiType subclass')

    cases = [
        ('ISBN-10 dashes', '0-306-40615-2'),
        ('ISBN-13 spaces', '978 0 306 40615 7'),
        ('ISBN-13 plain', '9780306406157'),
    ]

    for label, raw_isbn in cases:
        raw = {
            'title': 'The Book',
            'author': 'An Author',
            'price': '$12.99',
            'isbn': raw_isbn,
            'isbn13': '9780306406157',
        }
        result = BookListing.model_validate(raw)
        show_row(label, raw_isbn, result.isbn)

    console.print()
    console.print('  [dim]Non-13 digit ISBN when require_isbn13=True -> ValidationError:[/dim]')
    try:
        BookListing.model_validate(
            {'title': 'T', 'author': 'A', 'price': '$1.00', 'isbn': '0306406152', 'isbn13': '0306406152'}
        )
    except ValidationError as e:
        msgs = [err['msg'] for err in e.errors()]
        console.print(f'  [red]  x {msgs[0]}[/red]')


def demo_manifest() -> None:
    section('generate_manifest() — custom types visible to the AI')

    for cls in (ContactPage, BookListing):
        manifest = cls.generate_manifest()
        console.print(f'\n[bold]{cls.__name__}[/bold]')
        for line in manifest.splitlines():
            if line.startswith('|'):
                console.print(f'  [dim]{line}[/dim]')


if __name__ == '__main__':
    console.print(
        Panel(
            '[bold white]Yosoi Custom Types[/bold white]\n'
            '[dim]@register_coercion — one function, Field factory auto-generated[/dim]',
            style='blue',
        )
    )

    demo_phone()
    demo_isbn()
    demo_manifest()

    console.print()
    console.print('[bold green]All demos complete[/bold green]')
