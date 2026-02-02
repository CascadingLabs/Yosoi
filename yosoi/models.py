from pydantic import BaseModel, Field


class FieldSelectors(BaseModel):
    primary: str = Field(description='Most specific selector')
    fallback: str = Field(description='Less specific fallback')
    tertiary: str = Field(description="Generic selector or 'NA'")


class ScrapingConfig(BaseModel):
    headline: FieldSelectors
    author: FieldSelectors
    date: FieldSelectors
    body_text: FieldSelectors
    related_content: FieldSelectors
