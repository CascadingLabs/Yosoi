"""Demonstrates built-in validators and the Validators inner class.

Two examples — no boilerplate @field_validator needed:

1. Built-in type coercion  — ys.Price() strips currency automatically; ys.Title() strips whitespace
2. Validators inner class  — per-field transforms defined as plain static methods
"""

import os

from dotenv import load_dotenv

import yosoi as ys

load_dotenv()

config = ys.openrouter('llama-3.3-70b-versatile:free', os.environ['OPENROUTER_KEY'])


# -- Example 1: Built-in type coercion ----------------------------------------
# ys.Price() strips currency symbols and commas automatically — no @field_validator needed.
# ys.Title(), ys.Author(), etc. strip leading/trailing whitespace.
class Product(ys.Contract):
    """E-commerce product — price is always a clean float, no manual parsing required."""

    title: str = ys.Title()
    price: float = ys.Price(hint='Book price — always includes £ symbol')
    rating: str = ys.Rating(hint="Star rating written as a word e.g. 'Three'")


def example_1_builtin_coercion():
    """Show that ys.Price() coerces '£12.99' -> 12.99 without any extra code."""
    print('\n=== Example 1: Built-in type coercion ===')

    # Simulate what the pipeline returns after extraction
    raw = {'title': '  A Light in the Attic  ', 'price': '£12.99', 'rating': '  Three  '}
    result = Product.model_validate(raw)

    print(f'title  : {result.title!r}')  # 'A Light in the Attic'  (whitespace stripped)
    print(f'price  : {result.price!r}')  # 12.99  (float, £ stripped)
    print(f'rating : {result.rating!r}')  # 'Three'  (whitespace stripped)


# -- Example 2: Validators inner class ----------------------------------------
# Define per-field transforms as plain static methods inside a Validators class.
# They run before Pydantic's own field validation — no decorator ceremony required.
class BookStore(ys.Contract):
    """Book listing with custom per-field normalisation."""

    title: str = ys.Title()
    price: float = ys.Price(hint='Book price including currency symbol')
    category: str = ys.Field(hint='Genre or category label')

    class Validators:
        @staticmethod
        def title(v: str) -> str:
            """Truncate very long titles to 60 characters."""
            return v[:60].rstrip() + ('...' if len(v) > 60 else '')

        @staticmethod
        def category(v: str) -> str:
            """Normalise category to title case."""
            return v.strip().title()


def example_2_validators_class():
    """Show the Validators inner class applying field-level transforms."""
    print('\n=== Example 2: Validators inner class ===')

    raw = {
        'title': 'The Very Long Title That Goes On and On and Eventually Exceeds Sixty Characters',
        'price': '$1,234.56',
        'category': '  science fiction  ',
    }
    result = BookStore.model_validate(raw)

    print(f'title    : {result.title!r}')  # truncated at 60 chars
    print(f'price    : {result.price!r}')  # 1234.56 ($ and , stripped by ys.Price)
    print(f'category : {result.category!r}')  # 'Science Fiction'


if __name__ == '__main__':
    example_1_builtin_coercion()
    example_2_validators_class()
