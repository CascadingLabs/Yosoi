import yosoi as ys

class Article(ys.Contract):
    title: str=ys.Title()
    content: str=ys.Content()
    author: str=ys.Author()
    date: str=ys.Datetime(as_iso=True)
    comment_count: int=ys.Field(description="Number of comments on the article")

# Expected output
>>> article: Article = Article(title="How to scrape...", content="its easy peasy ...", author="Andrew", datetime="2025-01-01T00:00:00", comment_count=12)
