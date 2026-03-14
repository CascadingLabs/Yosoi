"""Tests for yosoi.core.fetcher.simple — SimpleFetcher."""

import pytest

from yosoi.core.fetcher.simple import SimpleFetcher

VALID_HTML = '<html><body>' + 'x' * 200 + '</body></html>'


class TestSimpleFetcherInit:
    def test_default_creates_session(self):
        """Default init creates an httpx client."""
        f = SimpleFetcher()
        assert f.client is not None
        assert f.timeout == 30
        assert f.rotate_user_agent is True

    def test_no_session(self):
        """use_session=False results in no client."""
        f = SimpleFetcher(use_session=False)
        assert f.client is None

    def test_custom_params(self):
        """Custom parameters are stored."""
        f = SimpleFetcher(timeout=10, min_delay=0, max_delay=0, randomize_headers=False)
        assert f.timeout == 10
        assert f.min_delay == 0
        assert f.randomize_headers is False


class TestSimpleFetcherHeaders:
    def test_randomized_headers(self):
        """When randomize_headers=True, headers have Sec-Fetch headers (Chrome UA)."""
        f = SimpleFetcher(randomize_headers=True, rotate_user_agent=False)
        headers = f._get_headers()
        assert 'User-Agent' in headers

    def test_static_headers(self):
        """When randomize_headers=False, static headers are returned."""
        f = SimpleFetcher(randomize_headers=False)
        headers = f._get_headers()
        assert 'User-Agent' in headers
        assert 'Accept' in headers


class TestSimpleFetcherFetch:
    @pytest.mark.asyncio
    async def test_short_response_returns_blocked(self, mocker):
        """Short/empty responses are marked as blocked."""
        f = SimpleFetcher(use_session=False, min_delay=0)
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<html/>'
        mock_resp.content = b'<html/>'
        mock_resp.headers = {}
        mocker.patch('httpx.AsyncClient.get', return_value=mock_resp)
        mocker.patch.object(f, '_apply_request_delay', return_value=None)

        result = await f.fetch('https://example.com')
        assert result.is_blocked is True
        assert 'too short' in result.block_reason

    @pytest.mark.asyncio
    async def test_successful_fetch(self, mocker):
        """Successful fetch returns FetchResult with html and metadata."""
        f = SimpleFetcher(use_session=False, min_delay=0)
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = VALID_HTML
        mock_resp.content = VALID_HTML.encode()
        mock_resp.headers = {}
        mocker.patch('httpx.AsyncClient.get', return_value=mock_resp)
        mocker.patch.object(f, '_apply_request_delay', return_value=None)

        result = await f.fetch('https://example.com')
        assert result.is_blocked is False
        assert result.html == VALID_HTML
        assert result.metadata is not None

    @pytest.mark.asyncio
    async def test_http_error_returns_error_result(self, mocker):
        """HTTP errors return a FetchResult with no html and block_reason."""
        import httpx

        f = SimpleFetcher(use_session=False, min_delay=0)
        mocker.patch('httpx.AsyncClient.get', side_effect=httpx.ConnectError('failed'))
        mocker.patch.object(f, '_apply_request_delay', return_value=None)

        result = await f.fetch('https://example.com')
        assert result.html is None
        assert result.block_reason is not None

    @pytest.mark.asyncio
    async def test_gzip_response_handled(self, mocker):
        """Gzip-encoded response starting with gzip magic bytes is decompressed."""
        import gzip

        f = SimpleFetcher(use_session=False, min_delay=0)
        raw_html = VALID_HTML
        compressed = gzip.compress(raw_html.encode())

        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '\x1f\x8b' + 'x' * 200  # starts with gzip magic
        mock_resp.content = compressed
        mock_resp.headers = {}
        mocker.patch('httpx.AsyncClient.get', return_value=mock_resp)
        mocker.patch.object(f, '_apply_request_delay', return_value=None)

        result = await f.fetch('https://example.com')
        assert result.html is not None

    @pytest.mark.asyncio
    async def test_uses_client_when_available(self, mocker):
        """When use_session=True, uses the stored client."""
        f = SimpleFetcher(use_session=True, min_delay=0)
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = VALID_HTML
        mock_resp.content = VALID_HTML.encode()
        mock_resp.headers = {}

        mocker.patch.object(f.client, 'get', return_value=mock_resp)
        mocker.patch.object(f, '_apply_request_delay', return_value=None)

        result = await f.fetch('https://example.com')
        assert result.html == VALID_HTML
        f.client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self, mocker):
        """Exiting context manager closes the client."""
        f = SimpleFetcher(use_session=True, min_delay=0)
        mock_aclose = mocker.patch.object(f.client, 'aclose', return_value=None)

        async with f:
            pass

        mock_aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_noop_when_no_client(self):
        """close() is safe when client is None."""
        f = SimpleFetcher(use_session=False)
        await f.close()  # should not raise


class TestRequestDelay:
    @pytest.mark.asyncio
    async def test_apply_request_delay_no_delay_when_min_zero(self):
        """When min_delay is 0, no delay is applied."""
        f = SimpleFetcher(use_session=False, min_delay=0, max_delay=0)
        # Should complete instantly without error
        await f._apply_request_delay()
        assert f.last_request_time > 0

    @pytest.mark.asyncio
    async def test_apply_request_delay_updates_last_request_time(self):
        """_apply_request_delay updates last_request_time."""
        f = SimpleFetcher(use_session=False, min_delay=0.01, max_delay=0.02)
        f.last_request_time = 0.0
        await f._apply_request_delay()
        assert f.last_request_time > 0

    @pytest.mark.asyncio
    async def test_apply_request_delay_waits_when_too_fast(self, mocker):
        """_apply_request_delay sleeps when requests are too fast."""
        import time

        f = SimpleFetcher(use_session=False, min_delay=0.5, max_delay=1.0)
        f.last_request_time = time.time()  # Just requested
        mock_sleep = mocker.patch('asyncio.sleep', return_value=None)
        await f._apply_request_delay()
        # Should have called sleep since elapsed < delay_needed
        mock_sleep.assert_called_once()


class TestEncodingFallback:
    @pytest.mark.asyncio
    async def test_unicode_decode_error_falls_back_to_utf8_replace(self, mocker):
        """When response.text raises, falls back to content.decode('utf-8')."""
        f = SimpleFetcher(use_session=False, min_delay=0)
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}

        # Make .text raise UnicodeDecodeError
        type(mock_resp).text = mocker.PropertyMock(side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'bad'))
        mock_resp.content = VALID_HTML.encode('utf-8')

        mocker.patch('httpx.AsyncClient.get', return_value=mock_resp)
        mocker.patch.object(f, '_apply_request_delay', return_value=None)

        result = await f.fetch('https://example.com')
        assert result.html is not None

    @pytest.mark.asyncio
    async def test_double_decode_error_falls_back_to_latin1(self, mocker):
        """When utf-8 decode also fails, falls back to latin-1."""
        f = SimpleFetcher(use_session=False, min_delay=0)
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}

        type(mock_resp).text = mocker.PropertyMock(side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'bad'))

        # Create a mock content that raises on utf-8 decode but works on latin-1
        mock_content = mocker.MagicMock()
        call_count = [0]

        def fake_decode(encoding, errors='strict'):
            call_count[0] += 1
            if call_count[0] == 1:
                raise UnicodeDecodeError('utf-8', b'', 0, 1, 'bad')
            return VALID_HTML

        mock_content.decode = fake_decode
        mock_resp.content = mock_content

        mocker.patch('httpx.AsyncClient.get', return_value=mock_resp)
        mocker.patch.object(f, '_apply_request_delay', return_value=None)

        result = await f.fetch('https://example.com')
        assert result.html is not None


class TestCreateFetcher:
    def test_create_simple_fetcher(self):
        """create_fetcher('simple') returns a SimpleFetcher."""
        from yosoi.core.fetcher import create_fetcher

        f = create_fetcher('simple')
        assert isinstance(f, SimpleFetcher)

    def test_create_unknown_fetcher_raises(self):
        """create_fetcher with unknown type raises ValueError."""
        from yosoi.core.fetcher import create_fetcher

        with pytest.raises(ValueError, match='Unknown fetcher type'):
            create_fetcher('playwright')
