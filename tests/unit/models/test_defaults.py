"""Tests for built-in default contracts."""

from yosoi.models.defaults import JobPosting, NewsArticle, Product, Video
from yosoi.models.selectors import FieldSelectors


def test_news_article_instantiates():
    article = NewsArticle.model_validate(
        {
            'headline': 'My Article',
            'author': 'Jane Doe',
            'date': '2024-01-15',
            'body_text': 'Some content here.',
            'related_content': 'Related links',
        }
    )
    assert article.headline == 'My Article'
    assert article.author == 'Jane Doe'


def test_product_instantiates():
    product = Product.model_validate(
        {
            'name': 'Widget',
            'price': '$9.99',
            'rating': '4.5',
            'reviews_count': 42,
            'description': 'A widget.',
            'availability': 'In Stock',
        }
    )
    assert product.name == 'Widget'
    assert product.price == 9.99


def test_video_instantiates():
    video = Video.model_validate(
        {
            'title': 'My Video',
            'channel': 'Tech Channel',
            'duration': '10:32',
            'views': 1000,
            'description': 'A great video.',
            'upload_date': '2024-06-15',
        }
    )
    assert video.title == 'My Video'
    assert video.channel == 'Tech Channel'


def test_job_posting_instantiates():
    job = JobPosting.model_validate(
        {
            'title': 'Software Engineer',
            'company': 'Tech Corp',
            'location': 'Remote',
            'salary': None,
            'posted_date': '2024-01-01',
            'description': 'Build software.',
        }
    )
    assert job.title == 'Software Engineer'
    assert job.salary is None


def test_news_article_to_selector_model_has_all_fields():
    SelectorModel = NewsArticle.to_selector_model()
    fields = SelectorModel.model_fields
    assert 'headline' in fields
    assert 'author' in fields
    assert 'date' in fields
    assert 'body_text' in fields
    assert 'related_content' in fields


def test_news_article_selector_model_instantiates():
    SelectorModel = NewsArticle.to_selector_model()
    instance = SelectorModel(
        headline=FieldSelectors(primary='h1'),
        author=FieldSelectors(primary='.author'),
        date=FieldSelectors(primary='time'),
        body_text=FieldSelectors(primary='article'),
        related_content=FieldSelectors(primary='aside'),
    )
    assert instance.headline.primary == 'h1'  # type: ignore[attr-defined]
