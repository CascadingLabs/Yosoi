from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from examples.google_maps.api_spec_maps import GoogleMapsReviews
from examples.google_maps.google_maps import GoogleMapsPlace, Schedule, build_maps_search_url
from examples.google_maps.reviews import (
    GoogleMapsReview,
    GoogleMapsReviewSample,
    _bounded_limit,
    _count_from_label,
    _review_share_url,
    _reviewer_id,
    scrape_reviews,
)
from examples.google_maps.stress_test import Target, _observe, _positive_int
from yosoi.models.results import FetchResult


def test_maps_flow_compiles_to_a3_nodes_and_binds_executor_inputs() -> None:
    plan = GoogleMapsReviews.compile(
        'https://example.test/maps',
        inputs={'limit': 3, 'max_scrolls': 5},
    )

    assert [node.id for node in plan.nodes] == [
        'navigate',
        'reviews_ready',
        'open_reviews',
        'open_sort_menu',
        'choose_sort',
        'load_reviews',
        'expand_reviews',
        'reviews',
    ]
    assert plan.nodes[-1].act.output_field == 'reviews'
    assert plan.nodes[-1].act.script is not None
    assert '{"limit":3}' in plan.nodes[-1].act.script


def test_maps_search_url_uses_stable_public_parameters() -> None:
    assert build_maps_search_url('Six Flags Over Georgia, Austell, GA') == (
        'https://www.google.com/maps/search/?api=1&query=Six+Flags+Over+Georgia%2C+Austell%2C+GA'
    )


def test_maps_search_url_rejects_blank_queries_and_omits_blank_place_ids() -> None:
    with pytest.raises(ValueError, match='must not be empty'):
        build_maps_search_url('   ')

    assert build_maps_search_url('Example', query_place_id='   ') == (
        'https://www.google.com/maps/search/?api=1&query=Example'
    )


def test_stress_cli_rejects_non_positive_concurrency() -> None:
    assert _positive_int('3') == 3
    with pytest.raises(argparse.ArgumentTypeError, match='at least 1'):
        _positive_int('0')


def test_stress_observation_ignores_detail_like_markup_before_primary_heading() -> None:
    fetched = FetchResult(
        url='https://example.test',
        status_code=200,
        fetch_time=0.25,
        html="""
          <button aria-label="Address: Wrong nearby address"></button>
          <h1>Primary &amp; Place</h1>
          <span aria-label="4.7 stars"></span><button aria-label="1,234 Reviews"></button>
          <button aria-label="Address: 1 Main St"></button>
          <a data-item-id="authority" href="https://primary.example/"></a>
          <button data-item-id="phone:tel:+15551234567"></button>
          <button aria-label="Plus code: QC9X+8X Atlanta"></button>
        """,
    )

    observation = _observe(
        Target('Primary Place', 'Atlanta, GA', 'https://example.test'),
        fetched,
        elapsed=0.5,
    )

    assert observation.detail_name == 'Primary & Place'
    assert observation.rating == 4.7
    assert observation.review_count == 1_234
    assert observation.address == '1 Main St'
    assert observation.website == 'https://primary.example/'
    assert observation.phone == '+15551234567'
    assert observation.plus_code == 'QC9X+8X Atlanta'


def test_maps_place_normalizes_live_detail_values() -> None:
    place = GoogleMapsPlace(
        name='Six Flags Over Georgia',
        rating='4.1 stars',
        review_count='(33,558)',
        address='275 Riverside Pkwy, Austell, GA 30168',
        phone='(770) 739-3400',
        website=('https://www.sixflags.com/overgeorgia?utm_source=googlebusinessprofile&utm_medium=organic'),
        plus_code='QC9X+8X Austell, Georgia',
    )

    assert place.rating == 4.1
    assert place.review_count == 33_558
    assert place.website == 'https://www.sixflags.com/overgeorgia'
    assert place.plus_code == 'QC9X+8X Austell, Georgia'


def test_schedule_normalizes_weekday_values_and_serializes_as_mapping() -> None:
    schedule = Schedule(
        timezone='America/New_York',
        monday='Monday, 08:00 a.m. - 8:00 Pm',
        tuesday=' CLOSED ',
        wednesday='24 HOURS',
        thursday='9 am to noon; 1:00 PM — 5:30 p.m.',
        friday=['18:00-03:00'],
        saturday='12–6\u202fPM',
    )

    assert schedule.monday == '8 AM–8 PM'
    assert schedule.thursday == '9 AM–12 PM, 1 PM–5:30 PM'
    assert schedule.friday == '6 PM–3 AM'
    assert schedule.saturday == '12 PM–6 PM'
    assert schedule.model_dump() == {
        'timezone': 'America/New_York',
        'days': {
            'monday': '8 AM–8 PM',
            'tuesday': 'Closed',
            'wednesday': 'Open 24 hours',
            'thursday': '9 AM–12 PM, 1 PM–5:30 PM',
            'friday': '6 PM–3 AM',
            'saturday': '12 PM–6 PM',
            'sunday': None,
        },
    }


@pytest.mark.parametrize(
    ('source', 'expected'),
    [
        ('9-5 PM', '9 AM–5 PM'),
        ('1-5 PM', '1 PM–5 PM'),
        ('9 AM-5', '9 AM–5 PM'),
        ('9 AM-11', '9 AM–11 AM'),
        ('6 PM-3', '6 PM–3 AM'),
        ('9-noon', '9 AM–12 PM'),
    ],
)
def test_schedule_infers_single_missing_meridiem_from_shortest_range(source: str, expected: str) -> None:
    assert Schedule(monday=source).monday == expected


def test_schedule_preserves_explicit_timezone_and_distinguishes_missing_from_closed() -> None:
    schedule = Schedule(timezone='CET', sunday='closed')

    assert schedule.timezone == 'CET'
    assert schedule.days['saturday'] is None
    assert schedule.days['sunday'] == 'Closed'


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('monday', '8-20', 'missing AM/PM'),
        ('tuesday', '8 AM until 8 PM', 'unrecognized opening-hours period'),
        ('wednesday', '13 PM-8 PM', 'invalid 12-hour time'),
        ('thursday', '8:75 AM-8 PM', 'invalid minute'),
        ('friday', '00:00-00:00', 'equal opening and closing times are ambiguous'),
        ('saturday', '12 AM-12 AM', 'equal opening and closing times are ambiguous'),
        ('timezone', 'Eastern Time', 'explicit IANA identifier'),
        ('timezone', 'America/Not_A_Zone', 'explicit IANA identifier'),
        ('timezone', 'America/New_York/', 'explicit IANA identifier'),
        ('timezone', 'posixrules', 'explicit IANA identifier'),
    ],
)
def test_schedule_rejects_ambiguous_or_invalid_values(field: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Schedule(**{field: value})


def test_maps_place_spec_round_trip_retains_normalization_and_validation() -> None:
    rehydrated = GoogleMapsPlace.to_spec().to_contract()
    place = rehydrated(
        name='Example',
        rating=4,
        review_count=1,
        address='1 Example St',
        plus_code=' QC9X+8X Example ',
        schedule={'monday': 'Monday, 08:00 a.m. - 8:00 Pm'},
    )

    assert place.plus_code == 'QC9X+8X Example'
    assert place.schedule.monday == '8 AM–8 PM'

    with pytest.raises(ValidationError, match='not a Google Maps Plus Code'):
        rehydrated(
            name='Example',
            rating=4,
            review_count=1,
            address='1 Example St',
            plus_code='1 Example St',
        )


def test_maps_place_exposes_selector_friendly_nested_schedule_fields() -> None:
    names = GoogleMapsPlace.discovery_field_names()

    assert 'schedule_monday' in names
    assert 'schedule_sunday' in names
    assert 'schedule_days' not in names

    place = GoogleMapsPlace(
        name='Example',
        rating=4,
        review_count=1,
        address='1 Example St',
        plus_code='QC9X+8X Example',
        schedule=Schedule(monday='8am-8pm'),
    )
    assert place.model_dump()['schedule']['days']['monday'] == '8 AM–8 PM'


def test_review_record_preserves_full_text_url_and_owner_response() -> None:
    review = GoogleMapsReview(
        review_id='review-1',
        review_url='https://maps.app.goo.gl/review-1',
        sample_rank=1,
        sort_mode='newest',
        rating=5,
        review_text='The complete public review text.',
        relative_date='2 months ago',
        reviewer_name='Example Reviewer',
        reviewer_id='12345',
        reviewer_profile_url='https://www.google.com/maps/contrib/12345/reviews?hl=en',
        reviewer_reviews_count=225,
        reviewer_photos_count=593,
        local_guide=True,
        owner_response_text='Thanks for visiting!',
        owner_response_relative_date='2 months ago',
    )

    assert review.review_text == 'The complete public review text.'
    assert review.review_url == 'https://maps.app.goo.gl/review-1'
    assert review.owner_response_text == 'Thanks for visiting!'


@pytest.mark.parametrize('field', ['review_id', 'review_url', 'relative_date', 'reviewer_name'])
def test_review_record_rejects_empty_required_provenance(field: str) -> None:
    values = {
        'review_id': 'review-1',
        'review_url': 'https://maps.app.goo.gl/review-1',
        'sample_rank': 1,
        'sort_mode': 'newest',
        'rating': 5,
        'relative_date': 'a month ago',
        'reviewer_name': 'Example',
    }
    values[field] = ''

    with pytest.raises(ValidationError):
        GoogleMapsReview(**values)


def test_review_record_rejects_non_google_share_url() -> None:
    with pytest.raises(ValidationError, match='Google Maps HTTPS share URL'):
        GoogleMapsReview(
            review_id='review-1',
            review_url='https://example.test/review-1',
            sample_rank=1,
            sort_mode='newest',
            rating=5,
            relative_date='a month ago',
            reviewer_name='Example',
        )


def test_review_sample_rejects_inconsistent_metadata() -> None:
    review = GoogleMapsReview(
        review_id='review-1',
        review_url='https://maps.app.goo.gl/review-1',
        sample_rank=1,
        sort_mode='newest',
        rating=5,
        relative_date='a month ago',
        reviewer_name='Example',
    )

    with pytest.raises(ValidationError, match='retrieved count must equal'):
        GoogleMapsReviewSample(
            business='Example',
            location='Atlanta, GA',
            source_url='https://www.google.com/maps/search/?api=1&query=Example',
            sort_mode='newest',
            requested_limit=2,
            retrieved_count=0,
            captured_at=datetime.now(timezone.utc),
            reviews=[review],
        )

    with pytest.raises(ValidationError, match='must include a timezone'):
        GoogleMapsReviewSample(
            business='Example',
            location='Atlanta, GA',
            source_url='https://www.google.com/maps/search/?api=1&query=Example',
            sort_mode='newest',
            requested_limit=1,
            retrieved_count=1,
            captured_at=datetime.now(),
            reviews=[review],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('share_mode', 'eval_results'),
    [
        ('direct', ['direct', 'https://maps.app.goo.gl/direct', True]),
        ('menu', ['menu', False, True, 'https://maps.app.goo.gl/menu', True]),
    ],
)
async def test_review_share_url_supports_direct_and_action_menu_paths(
    mocker, share_mode: str, eval_results: list[object]
) -> None:
    tab = mocker.Mock()
    tab.eval_js = mocker.AsyncMock(side_effect=eval_results)

    assert await _review_share_url(tab, 'review-1') == f'https://maps.app.goo.gl/{share_mode}'
    assert tab.eval_js.await_count == len(eval_results)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('overrides', 'message'),
    [
        ({'limit': 101}, 'between 1 and 100'),
        ({'business': '  '}, 'business and location must not be empty'),
        ({'location': ''}, 'business and location must not be empty'),
        ({'sort_mode': 'random'}, 'unsupported review sort mode'),
        ({'fetcher_type': 'firefox'}, 'unsupported fetcher type'),
    ],
)
async def test_scrape_reviews_rejects_invalid_programmatic_inputs_before_browser_use(
    overrides: dict[str, object], message: str
) -> None:
    kwargs = {
        'business': 'Example',
        'location': 'Atlanta, GA',
        'limit': 5,
        'sort_mode': 'newest',
        'fetcher_type': 'headless',
        **overrides,
    }
    with pytest.raises(ValueError, match=message):
        await scrape_reviews(**kwargs)  # type: ignore[arg-type]


def test_review_contributor_metadata_parsing() -> None:
    label = 'Local Guide · 2,447 reviews · 42,972 photos'
    profile = 'https://www.google.com/maps/contrib/112478094627247528494/reviews?hl=en'

    assert _count_from_label(label, 'reviews?') == 2_447
    assert _count_from_label(label, 'photos?') == 42_972
    assert _reviewer_id(profile) == '112478094627247528494'
    assert _bounded_limit('100') == 100
    with pytest.raises(argparse.ArgumentTypeError, match='between 1 and 100'):
        _bounded_limit('101')


@pytest.mark.parametrize('plus_code', ['CF2+CF', 'CF2CF+GH', 'CF2CFGH+JM'])
def test_maps_place_rejects_odd_length_plus_code_prefixes(plus_code: str) -> None:
    with pytest.raises(ValidationError, match='not a Google Maps Plus Code'):
        GoogleMapsPlace(name='Example', rating=4, review_count=1, address='1 Example St', plus_code=plus_code)


def test_maps_place_rejects_address_as_plus_code() -> None:
    with pytest.raises(ValidationError, match='not a Google Maps Plus Code'):
        GoogleMapsPlace(
            name='Six Flags Over Georgia',
            rating=4.1,
            review_count=33_558,
            address='275 Riverside Pkwy, Austell, GA 30168',
            plus_code='275 Riverside Pkwy, Austell, GA 30168',
        )
