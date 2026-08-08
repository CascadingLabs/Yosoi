"""Offline tests for the dependency-free benchmark client."""

from pathlib import Path

from client import image_dimensions, payload


def test_png_dimensions_and_multimodal_payload(tmp_path: Path) -> None:
    """The client preserves image metadata and emits OpenAI multimodal content."""
    image = tmp_path / 'capture.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8 + (640).to_bytes(4, 'big') + (480).to_bytes(4, 'big'))

    assert image_dimensions(image) == (640, 480)
    body = payload('model', 'describe', image, 32)
    content = body['messages'][0]['content']
    assert content[0] == {'type': 'text', 'text': 'describe'}
    assert content[1]['type'] == 'image_url'
    assert content[1]['image_url']['url'].startswith('data:image/png;base64,')
