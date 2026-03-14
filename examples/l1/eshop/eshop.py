# Example Idea
#
#
# 1. show that I can get product contract, with price, in stock (bool), and category :: pretty simple
# 2. show how to filter/ field validate against is_sponsered
# show formatting and
#

import asyncio

import yosoi as ys

MODEL_USED = 'meta-llama/llama-3.3-70b-instruct:free'
MODEL_USED = 'stepfun/step-3.5-flash:free'
# why can't I go to defition from this???
config = ys.openrouter(MODEL_USED)


class Product(ys.Contract):
    name: str = ys.Title(description='Product name or title')
    price: float | None = ys.Price(description='Product price (including currency symbol)')
    rating: float | str = ys.Rating(description='Star rating or review score')
    reviews_count: int | None = ys.Field(description='Number of reviews or ratings')
    description: str = ys.BodyText(description='Product description or summary')
    availability: str = ys.Field(description='Stock status (e.g. "In Stock", "Out of Stock")')


pipeline = ys.Pipeline(llm_config=config, contract=Product)
asyncio.run(pipeline.process_url('https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing', force=True))
