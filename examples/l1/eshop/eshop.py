# Example Idea
#
#
# 1. show that I can get product contract, with price, in stock (bool), and category :: pretty simple
# 2. show how to filter/ field validate against is_sponsered
# show formatting and
#

import asyncio
import re

import yosoi as ys

# MODEL_USED = 'meta-llama/llama-3.3-70b-instruct:free'
# MODEL_USED = 'stepfun/step-3.5-flash:free'
# MODEL_USED = 'llama-3.3-70b-versatile'
# why can't I go to defition from this???
# config = ys.openrouter(MODEL_USED)
# config = ys.groq(MODEL_USED)


class Product(ys.Contract):
    name: str = ys.Title(description='Product name or title')
    price: float | None = ys.Price(description='Product price (including currency symbol)')
    rating: float = ys.Rating(description='review score as a number')
    reviews_count: int | None = ys.Field(description='Number of reviews or ratings')
    description: str = ys.BodyText(description='Product description or summary')
    availability: str = ys.Field(description='Stock status (e.g. "In Stock", "Out of Stock")')
    is_instock: bool | None = ys.Field(description='Whether the product is in stock')

    class Validators:
        @staticmethod
        def rating(v: object) -> float:
            # Selector returns e.g. "★ ★ ★ ★   ☆   (47)" — count filled stars
            return float(str(v).count('★'))

        @staticmethod
        def reviews_count(v: object) -> int | None:
            if v is None:
                return None
            m = re.search(r'\d+', str(v))
            return int(m.group()) if m else None

        @staticmethod
        def is_instock(v: object) -> bool | None:
            if v is None:
                return None
            text = str(v).strip().lower()
            return not ('out of stock' in text or not text)


# pipeline = ys.Pipeline(llm_config=config, contract=Product)
pipeline = ys.Pipeline(llm_config='openrouter:stepfun/step-3.5-flash:free', contract=Product)
asyncio.run(pipeline.process_url('https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing'))


# # ---------------------------------------------------------------------------
# # Using default contracts: ys.Product, ys.NewsArticle, ys.Video, ys.JobPosting
# # ---------------------------------------------------------------------------


# def main_default() -> None:
#     """Use ys.Product directly — zero boilerplate."""
#     pipeline = ys.Pipeline(llm_config=config, contract=ys.Product)
#     asyncio.run(pipeline.process_url('https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing', force=True))


# def main_subclass() -> None:
#     """Subclass ys.Product to add extra fields or validators."""

#     class DetailedProduct(ys.Product):
#         category: str = ys.Field(description='Product category (e.g. "Swords", "Armor")')
#         in_stock: bool = ys.Field(description='Whether the item is currently in stock')

#         class Validators:
#             @staticmethod
#             def category(v: str) -> str:
#                 return v.strip().title()

#     pipeline = ys.Pipeline(llm_config=config, contract=DetailedProduct)
#     asyncio.run(pipeline.process_url('https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing', force=True))


# def main_override() -> None:
#     """Subclass ys.Product and override an existing field."""

#     class StrictProduct(ys.Product):
#         # Override: make price required (no None) and add a currency hint
#         price: float = ys.Price(description='Product price in USD', currency='USD')
#         # Override: tighten rating to float only
#         rating: float = ys.Rating(description='Numeric star rating (1-5)')

#     pipeline = ys.Pipeline(llm_config=config, contract=StrictProduct)
#     asyncio.run(pipeline.process_url('https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing', force=True))


# if __name__ == '__main__':
#     # Pick which example to run:
#     # main_default()      # use ys.Product as-is
#     # main_subclass()     # extend with extra fields
#     main_override()  # override existing fields
