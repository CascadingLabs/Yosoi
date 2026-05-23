"""Unit tests for the shared RequestUsage builder used by both backends."""

from pydantic_ai.usage import RequestUsage

from yosoi.integrations.utils.usage import build_request_usage


def test_maps_all_buckets_and_reasoning_rides_in_details():
    usage = build_request_usage(
        input_tokens=150,
        output_tokens=50,
        cache_read_tokens=8,
        cache_write_tokens=4,
        reasoning_tokens=12,
    )
    assert usage.input_tokens == 150
    assert usage.output_tokens == 50
    assert usage.cache_read_tokens == 8
    assert usage.cache_write_tokens == 4
    assert usage.details.get('reasoning_tokens') == 12


def test_tolerates_none_counts():
    """Callers pass raw.get(...) straight through; None coerces to 0."""
    usage = build_request_usage(input_tokens=None, output_tokens=10)
    assert usage.input_tokens == 0
    assert usage.output_tokens == 10


def test_zero_reasoning_keeps_details_empty():
    """Zero reasoning tokens are omitted so the Langfuse details panel stays clean."""
    assert build_request_usage(input_tokens=1, output_tokens=1, reasoning_tokens=0).details == {}


def test_all_defaults_is_empty_usage():
    assert build_request_usage() == RequestUsage()
