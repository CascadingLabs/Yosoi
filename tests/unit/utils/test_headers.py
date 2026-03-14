"""Tests for yosoi.utils.headers — UserAgentRotator and HeaderGenerator."""

from yosoi.utils.headers import HeaderGenerator, UserAgentRotator


class TestUserAgentRotator:
    def test_get_random_returns_string(self):
        """get_random returns a non-empty user agent string."""
        ua = UserAgentRotator.get_random()
        assert isinstance(ua, str)
        assert len(ua) > 0

    def test_get_chrome_windows(self):
        """get_chrome_windows returns a Chrome-on-Windows UA."""
        ua = UserAgentRotator.get_chrome_windows()
        assert 'Chrome' in ua
        assert 'Windows' in ua
        assert 'Edg' not in ua

    def test_get_firefox(self):
        """get_firefox returns a Firefox UA."""
        ua = UserAgentRotator.get_firefox()
        assert 'Firefox' in ua

    def test_user_agents_pool_not_empty(self):
        """The UA pool contains multiple agents."""
        assert len(UserAgentRotator.USER_AGENTS) > 5


class TestHeaderGenerator:
    def test_generate_headers_has_required_keys(self):
        """Generated headers include required browser headers."""
        headers = HeaderGenerator.generate_headers()
        assert 'User-Agent' in headers
        assert 'Accept' in headers
        assert 'Accept-Language' in headers
        assert 'Accept-Encoding' in headers

    def test_custom_user_agent(self):
        """Custom user agent is used when provided."""
        headers = HeaderGenerator.generate_headers(user_agent='CustomUA/1.0')
        assert headers['User-Agent'] == 'CustomUA/1.0'

    def test_chrome_ua_gets_sec_fetch_headers(self):
        """Chrome user agent gets Sec-Fetch headers."""
        chrome_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
        headers = HeaderGenerator.generate_headers(user_agent=chrome_ua)
        assert 'Sec-Fetch-Dest' in headers
        assert headers['Sec-Fetch-Site'] == 'none'

    def test_firefox_ua_no_sec_fetch_headers(self):
        """Firefox user agent does not get Sec-Fetch headers."""
        firefox_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
        headers = HeaderGenerator.generate_headers(user_agent=firefox_ua)
        assert 'Sec-Fetch-Dest' not in headers

    def test_referer_added_when_provided(self):
        """Referer header is added when provided."""
        headers = HeaderGenerator.generate_headers(referer='https://google.com')
        assert headers['Referer'] == 'https://google.com'

    def test_referer_changes_sec_fetch_site(self):
        """With referer, Sec-Fetch-Site changes to same-origin for Chrome."""
        chrome_ua = 'Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36'
        headers = HeaderGenerator.generate_headers(user_agent=chrome_ua, referer='https://site.com')
        assert headers['Sec-Fetch-Site'] == 'same-origin'

    def test_no_referer_by_default(self):
        """No Referer header when none provided."""
        firefox_ua = 'Mozilla/5.0 Firefox/121.0 Gecko/20100101'
        headers = HeaderGenerator.generate_headers(user_agent=firefox_ua)
        assert 'Referer' not in headers
