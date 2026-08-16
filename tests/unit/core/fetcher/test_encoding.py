"""Tests for yosoi.core.fetcher.encoding — charset resolution beyond the HTTP header.

Regression coverage for CAS-228: only the ``Content-Type: charset=`` header was honored,
so every other way the web declares an encoding produced mojibake.
"""

import pytest

from yosoi.core.fetcher.encoding import charset_from_content_type, charset_from_meta, decode_html
from yosoi.core.fetcher.simple import SimpleFetcher

JAPANESE = '価格は1000円です'
CYRILLIC = 'Цена составляет 1000 рублей'


def _page(body: str, *, meta: str | None, encoding: str) -> bytes:
    head = f'<meta charset="{meta}">' if meta else ''
    return f'<html><head>{head}</head><body><p>{body}</p></body></html>'.encode(encoding)


class TestCharsetFromContentType:
    @pytest.mark.parametrize(
        ('header', 'expected'),
        [
            ('text/html; charset=shift_jis', 'shift_jis'),
            ('text/html;charset="windows-1251"', 'windows-1251'),
            ('text/html; Charset=UTF-8', 'UTF-8'),
            ('text/html', None),
            ('text/html; charset=', None),
            (None, None),
        ],
    )
    def test_parses_charset_parameter(self, header, expected):
        assert charset_from_content_type(header) == expected


class TestCharsetFromMeta:
    def test_html5_meta_charset(self):
        assert charset_from_meta(b'<html><head><meta charset="shift_jis"></head>') == 'shift_jis'

    def test_legacy_http_equiv_meta(self):
        html = b'<meta http-equiv="Content-Type" content="text/html; charset=windows-1251">'
        assert charset_from_meta(html) == 'windows-1251'

    def test_no_declaration(self):
        assert charset_from_meta(b'<html><head><title>hi</title></head>') is None

    def test_ignores_declaration_past_the_prescan_window(self):
        html = b'<!--' + b'x' * 5000 + b'--><meta charset="shift_jis">'
        assert charset_from_meta(html) is None


class TestDecodeHtml:
    def test_correct_header_wins(self):
        content = _page(JAPANESE, meta=None, encoding='shift_jis')
        text, encoding = decode_html(content, declared='shift_jis')
        assert JAPANESE in text
        assert encoding == 'shift_jis'

    def test_lying_header_falls_through_to_meta(self):
        content = _page(JAPANESE, meta='shift_jis', encoding='shift_jis')
        text, encoding = decode_html(content, declared='utf-8')
        assert JAPANESE in text
        assert encoding == 'shift_jis'

    def test_meta_only_declaration(self):
        content = _page(CYRILLIC, meta='windows-1251', encoding='windows-1251')
        text, encoding = decode_html(content, declared=None)
        assert CYRILLIC in text
        assert encoding == 'windows-1251'

    def test_nothing_declared_uses_byte_detection(self):
        content = _page(CYRILLIC, meta=None, encoding='windows-1251')
        text, _ = decode_html(content, declared=None)
        assert '�' not in text
        assert CYRILLIC in text

    def test_unknown_codec_name_is_skipped(self):
        content = _page(JAPANESE, meta='shift_jis', encoding='shift_jis')
        text, encoding = decode_html(content, declared='not-a-real-charset')
        assert JAPANESE in text
        assert encoding == 'shift_jis'

    def test_utf8_bom_is_honored_over_a_wrong_header(self):
        content = '﻿' + f'<html><body>{JAPANESE}</body></html>'
        text, encoding = decode_html(content.encode('utf-8-sig'), declared='shift_jis')
        assert JAPANESE in text
        assert encoding == 'utf-8-sig'

    def test_plain_utf8_without_any_declaration(self):
        text, encoding = decode_html(_page(JAPANESE, meta=None, encoding='utf-8'), declared=None)
        assert JAPANESE in text
        assert encoding == 'utf-8'

    def test_empty_body(self):
        assert decode_html(b'', declared='shift_jis') == ('', 'utf-8')

    def test_undecodable_bytes_fall_back_to_lossy_utf8(self):
        text, encoding = decode_html(b'\x81\x00\xff\xfe rubbish \x00\x81', declared=None)
        assert encoding == 'utf-8'
        assert isinstance(text, str)


class TestSimpleFetcherDecoding:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ('declared', 'meta'),
        [
            ('shift_jis', None),  # correct header
            ('utf-8', 'shift_jis'),  # header lies, meta is right
            (None, 'shift_jis'),  # meta only
            (None, None),  # nothing declared, byte detection
        ],
    )
    async def test_non_utf8_page_is_not_mojibake(self, mocker, declared, meta):
        body = JAPANESE + 'あ' * 200
        content = _page(body, meta=meta, encoding='shift_jis')
        headers = {'content-type': f'text/html; charset={declared}'} if declared else {'content-type': 'text/html'}

        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = content
        mock_resp.headers = headers
        mocker.patch('httpx2.AsyncClient.get', return_value=mock_resp)

        fetcher = SimpleFetcher(use_session=False, min_delay=0)
        mocker.patch.object(fetcher, '_apply_request_delay', return_value=None)
        result = await fetcher.fetch('https://example.jp/')

        assert result.html is not None
        assert JAPANESE in result.html
        assert '�' not in result.html
