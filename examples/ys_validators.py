"""@ys.validator — declarative field and model validators for Contracts.

Two decorator flavors:

  1. @ys.validator("field")  — Atomic field guard (classmethod).
     Runs post-coercion. Ideal for hallucination guards that reject bad data
     during discovery.

  2. @ys.validator()         — Holistic model guard (instance method).
     Runs post-construction. Ideal for cross-field logic checks during
     extraction.

Run with:
    uv run python examples/ys_validators.py
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import yosoi as ys
from yosoi.models.contract import Contract

console = Console()


# ---------------------------------------------------------------------------
# Contract definition
# ---------------------------------------------------------------------------


class ProductContract(Contract):
    """E-commerce product with field + model validators."""

    name: str = ys.Title(description='Product name')
    price: float = ys.Price(description='List price')
    sale_price: float = ys.Price(description='Sale price', default=0.0)
    sku: str
    in_stock: bool = True

    class Validators:
        """Step 1: pre-coercion transforms (runs before Price strips currency)."""

        @staticmethod
        def name(v: str) -> str:
            # Normalize whitespace and remove trademark symbols
            return v.replace('\u2122', '').replace('\u00ae', '').strip()

    # Step 3: atomic field validator — the "hallucination guard"
    @ys.validator('sku')
    @classmethod
    def validate_sku_format(cls, v: str) -> str:
        """Reject SKUs that don't match the site's known format."""
        if not v.startswith('PRD-'):
            raise ValueError(f"SKU '{v}' doesn't match expected PRD-XXXX format")
        return v.upper()

    # Another field validator targeting two fields at once
    @ys.validator('name', 'sku')
    @classmethod
    def reject_placeholder_text(cls, v: str) -> str:
        """Catch common LLM hallucination patterns."""
        lowered = v.lower()
        if any(placeholder in lowered for placeholder in ['n/a', 'lorem', 'placeholder', 'example']):
            raise ValueError(f"Detected placeholder text: '{v}'")
        return v

    # Step 5: holistic model validator — the "logic guard"
    @ys.validator()
    def validate_sale_logic(self) -> 'ProductContract':
        """Sale price must not exceed list price."""
        if self.sale_price > self.price:
            raise ValueError(f'Sale price ${self.sale_price:.2f} exceeds list price ${self.price:.2f}')
        return self

    @ys.validator()
    def validate_sale_requires_stock(self) -> 'ProductContract':
        """A sale on an out-of-stock item is suspicious."""
        if self.sale_price > 0 and not self.in_stock:
            raise ValueError('Sale price set on out-of-stock item — likely stale data')
        return self


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


def try_validate(label: str, data: dict) -> None:
    """Attempt validation and print the result or error."""
    try:
        result = ProductContract.model_validate(data)
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style='dim')
        table.add_column(style='green')
        for field_name in ProductContract.model_fields:
            table.add_row(field_name, repr(getattr(result, field_name)))
        console.print(f'  [bold green]PASS[/bold green] {label}')
        console.print(table)
    except Exception as e:
        msg = e.errors()[0]['msg'] if hasattr(e, 'errors') else str(e)
        console.print(f'  [bold red]FAIL[/bold red] {label}')
        console.print(f'         [red]{msg}[/red]')
    console.print()


def main() -> None:
    console.print(
        Panel(
            '[bold white]@ys.validator — Field & Model Guards[/bold white]\n'
            '[dim]Hallucination guards for discovery, logic guards for extraction[/dim]',
            style='blue',
        )
    )

    # --- Happy path: everything valid ---
    console.print(Panel('[cyan]Happy Path[/cyan]', expand=False))
    try_validate(
        'All fields valid',
        {
            'name': 'Wireless Headphones™',
            'price': '$149.99',
            'sale_price': '$99.99',
            'sku': 'PRD-4821',
            'in_stock': True,
        },
    )

    # --- Field validator: bad SKU format ---
    console.print(Panel('[cyan]@ys.validator("sku") — Hallucination Guard[/cyan]', expand=False))
    try_validate(
        'SKU wrong format (AI picked up wrong element)',
        {
            'name': 'Bluetooth Speaker',
            'price': '$79.99',
            'sku': 'SKU-9999',  # Wrong prefix
        },
    )

    # --- Field validator: placeholder text ---
    console.print(Panel('[cyan]@ys.validator("name", "sku") — Placeholder Guard[/cyan]', expand=False))
    try_validate(
        'Name contains placeholder text',
        {
            'name': 'Lorem Ipsum Product',
            'price': '$29.99',
            'sku': 'PRD-0001',
        },
    )

    # --- Model validator: sale > price ---
    console.print(Panel('[cyan]@ys.validator() — Cross-Field Logic Guard[/cyan]', expand=False))
    try_validate(
        'Sale price exceeds list price (AI swapped the fields)',
        {
            'name': 'USB-C Cable',
            'price': '$12.99',
            'sale_price': '$24.99',  # Higher than list price
            'sku': 'PRD-1100',
        },
    )

    # --- Model validator: sale on out-of-stock ---
    try_validate(
        'Sale on out-of-stock item (stale selector data)',
        {
            'name': 'Mechanical Keyboard',
            'price': '$189.00',
            'sale_price': '$139.00',
            'sku': 'PRD-7700',
            'in_stock': False,
        },
    )

    # --- Show the full validation pipeline order ---
    console.print(
        Panel(
            '[bold]Validation Pipeline Order[/bold]\n\n'
            '[dim]1.[/dim] [white]Validators inner class[/white]    [dim]— pre-coercion transforms (strip TM symbols)[/dim]\n'
            '[dim]2.[/dim] [white]ys.Price() / ys.Title()[/white]   [dim]— semantic type coercion ($149.99 → 149.99)[/dim]\n'
            '[dim]3.[/dim] [white]@ys.validator("field")[/white]     [dim]— atomic field guards (SKU format, placeholders)[/dim]\n'
            '[dim]4.[/dim] [white]Pydantic validation[/white]        [dim]— type checking, required fields[/dim]\n'
            '[dim]5.[/dim] [white]@ys.validator()[/white]            [dim]— holistic model guards (sale < price)[/dim]',
            style='blue',
            title='Pipeline',
        )
    )


if __name__ == '__main__':
    main()
