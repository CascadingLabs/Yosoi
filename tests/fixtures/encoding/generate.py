"""Regenerate the byte fixtures in this directory.

Run with ``uv run python tests/fixtures/encoding/generate.py``. The fixtures are committed
as bytes (not text) on purpose: the whole point of CAS-228 is what happens *before* bytes
become ``str``, so a text fixture read through Python's default UTF-8 would erase the bug.

The declaration patterns mirror the ones observed on the live web (see
``tests/smoke/test_encoding_live.py``): header-only, meta-only, both, a lying header,
and nothing declared at all.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

JAPANESE = '価格は1000円です。送料は無料。'
CYRILLIC = 'Цена составляет 1000 рублей. Доставка бесплатная.'
KOREAN = '가격은 1000원입니다. 배송비는 무료입니다.'
CHINESE = '价格是1000元。免运费。'
GERMAN = 'Der Preis beträgt 1000 Euro. Größe: mittel. Grüße!'

# filename -> (encoding, meta declaration or None, marker text, HTTP charset the server
# should send or None, the encoding decode_html is expected to settle on).
#
# The expected encoding is ``None`` where only byte detection can decide and several
# codecs decode the bytes identically: undeclared single-byte Latin text is genuinely
# ambiguous (cp1250 and cp1252 agree on German umlauts), so the contract there is
# "readable text", not a specific codec name.
CASES: dict[str, tuple[str, str | None, str, str | None, str | None]] = {
    'shift_jis_header_only.html': ('shift_jis', None, JAPANESE, 'shift_jis', 'shift_jis'),
    'shift_jis_meta_only.html': ('shift_jis', 'meta', JAPANESE, None, 'shift_jis'),
    'shift_jis_header_lies.html': ('shift_jis', 'meta', JAPANESE, 'utf-8', 'shift_jis'),
    'shift_jis_undeclared.html': ('shift_jis', None, JAPANESE, None, 'cp932'),
    'windows1251_meta_only.html': ('windows-1251', 'meta', CYRILLIC, None, 'windows-1251'),
    'koi8r_header_only.html': ('koi8-r', None, CYRILLIC, 'koi8-r', 'koi8-r'),
    'gb18030_http_equiv.html': ('gb18030', 'http-equiv', CHINESE, None, 'gb18030'),
    'euc_kr_meta_and_header.html': ('euc-kr', 'meta', KOREAN, 'euc-kr', 'euc-kr'),
    'latin1_undeclared.html': ('iso-8859-1', None, GERMAN, None, None),
    'utf8_bom_wrong_header.html': ('utf-8-sig', None, JAPANESE, 'shift_jis', 'utf-8-sig'),
    'utf8_plain.html': ('utf-8', 'meta', JAPANESE, 'utf-8', 'utf-8'),
}


def _document(encoding: str, meta_style: str | None, marker: str) -> str:
    declared = 'utf-8' if encoding == 'utf-8-sig' else encoding
    if meta_style == 'meta':
        head = f'<meta charset="{declared}">'
    elif meta_style == 'http-equiv':
        head = f'<meta http-equiv="Content-Type" content="text/html; charset={declared}">'
    else:
        head = ''
    # Padding keeps every fixture over SimpleFetcher's min_content_length so the fetcher
    # path exercises decoding rather than the too-short guard.
    padding = '<p>' + ('ABCDEFGHIJ' * 30) + '</p>'
    # The trailing newline keeps the committed bytes stable under the end-of-file-fixer
    # hook; 0x0A encodes identically in every codec used here, so decoding is unaffected.
    return (
        f'<!doctype html><html><head>{head}<title>{marker}</title></head>'
        f'<body><h1>{marker}</h1><p class="price">{marker}</p>{padding}</body></html>\n'
    )


def main() -> None:
    manifest: dict[str, dict[str, str | None]] = {}
    for filename, (encoding, meta_style, marker, http_charset, expected) in CASES.items():
        (HERE / filename).write_bytes(_document(encoding, meta_style, marker).encode(encoding))
        manifest[filename] = {
            'http_charset': http_charset,
            'expected_encoding': expected,
            'marker': marker,
        }
    (HERE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
