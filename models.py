from pydantic import BaseModel


class SelectorStrategy(BaseModel):
    primary: str
    fallback: str
    tertiary: str


class ScrapingConfig(BaseModel):
    headline: SelectorStrategy
    author: SelectorStrategy
    date: SelectorStrategy
    body_text: SelectorStrategy
    related_content: SelectorStrategy
