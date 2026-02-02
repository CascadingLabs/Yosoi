from pydantic import BaseModel, Field


class FieldSelectors(BaseModel):
    primary: str = Field(description='Most specific selector')
    fallback: str = Field(description='Less specific fallback')
    tertiary: str = Field(description="Generic selector or 'NA'")


# TODO Make this a dynamic class. Perhaps include a way for users to define via pydantic models?
# >> Maybe we make a custom pydantic model that can be used to define what is being scraped?
# >> This might look like YosoiContent(BaseModel):
# >>     url: str FieldSelectors
# >>     date: DATETIME FieldSelector
# >>     body_text: str
# >>     related_content: str
# >> And then we can use this to generate the ScrapingConfig dynamically?


class ScrapingConfig(BaseModel):
    headline: FieldSelectors
    author: FieldSelectors
    date: FieldSelectors
    body_text: FieldSelectors
    related_content: FieldSelectors
