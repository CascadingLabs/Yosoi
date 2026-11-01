"""Fail-closed fixture validation and attribution for actual image operations."""

from __future__ import annotations

import hashlib
import struct
import zlib
from typing import Any

from media_documents_conformance import _mapping_checks, _plain

import parity

FIXTURE_KIND = "yosoi-image-surface-conformance-fixtures"
RESULT_KIND = "yosoi-python-rust-conformance-results"
EVIDENCE_KIND = "yosoi-python-rust-conformance"
CASE_NAMES = frozenset(
    {
        "decode-direct",
        "image-reader",
        "direct",
        "overview",
        "overview-fits",
        "resize",
        "crop-rect",
        "crop-reference",
        "coordinate-map",
        "native-reference",
        "shared-reference",
        "root-artifact",
        "read-overview",
        "read-expand",
        "read-inspect",
        "read-parent",
        "screenshot-root",
        "video-frame-root",
        "archive-portable",
        "jpeg-decode-direct",
        "jpeg-reader",
        "jpeg-direct",
        "jpeg-overview",
        "jpeg-crop",
    }
)
ERROR_NAMES = frozenset(
    {
        "foreign-reference",
        "crop-outside",
        "crop-zero-budget",
        "crop-byte-bound",
        "overview-zero",
        "resize-zero",
        "nested-root",
        "map-outside",
        "search-unavailable",
        "decode-byte-bound",
    }
)
CASE_METHODS = {
    "decode-direct": "PixelArtifact::decode_image_document",
    "image-reader": "ImageSurface::from_image_document",
    "direct": "ImageSurface::direct_image",
    "overview": "ImageSurface::overview_image",
    "overview-fits": "ImageSurface::overview_image",
    "resize": "ImageSurface::resize_image",
    "crop-rect": "ImageSurface::crop_rect",
    "crop-reference": "ImageSurface::crop",
    "coordinate-map": "PixelArtifact::map_rect_to_source",
    "native-reference": "ImageSurface::native_reference",
    "shared-reference": "ImageSurface::reference",
    "root-artifact": "ImageSurface::from_pixel_artifact",
    "screenshot-root": "ImageSurface::from_pixel_artifact",
    "video-frame-root": "ImageSurface::from_pixel_artifact",
    "archive-portable": "PixelArtifact::read_from",
    "jpeg-decode-direct": "PixelArtifact::decode_image_document",
    "jpeg-reader": "ImageSurface::from_image_document",
    "jpeg-direct": "ImageSurface::direct_image",
    "jpeg-overview": "ImageSurface::overview_image",
    "jpeg-crop": "ImageSurface::crop_rect",
    **dict.fromkeys(
        ("read-overview", "read-expand", "read-inspect", "read-parent"),
        "model::SurfaceRead::read",
    ),
    "foreign-reference": "ImageSurface::crop",
    "crop-outside": "ImageSurface::crop_rect",
    "crop-zero-budget": "ImageSurface::crop_rect",
    "crop-byte-bound": "ImageSurface::crop_rect",
    "overview-zero": "ImageSurface::overview_image",
    "resize-zero": "ImageSurface::resize_image",
    "nested-root": "ImageSurface::from_pixel_artifact",
    "map-outside": "PixelArtifact::map_rect_to_source",
    "search-unavailable": "model::SurfaceRead::read",
    "decode-byte-bound": "PixelArtifact::decode_image_document",
}


def rgba_png(payload: bytes) -> tuple[int, int, list[int]]:
    """Independently decode bounded RGB8/RGBA8 PNG fixtures into RGBA pixels."""
    if not payload.startswith(b"\x89PNG\r\n\x1a\n") or len(payload) > 8 * 1024 * 1024:
        raise ValueError("image fixture is not a bounded PNG")
    cursor, compressed, dimensions, ended = 8, bytearray(), None, False
    while cursor < len(payload):
        if len(payload) - cursor < 12:
            raise ValueError("truncated image fixture chunk")
        size = struct.unpack_from(">I", payload, cursor)[0]
        tag = payload[cursor + 4 : cursor + 8]
        end = cursor + 8 + size
        if end + 4 > len(payload):
            raise ValueError("truncated image fixture chunk payload")
        data = payload[cursor + 8 : end]
        if zlib.crc32(tag + data) != struct.unpack_from(">I", payload, end)[0]:
            raise ValueError("image fixture PNG checksum mismatch")
        if tag == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            if (
                not (0 < width <= 8192 and 0 < height <= 8192)
                or (depth, compression, filtering, interlace) != (8, 0, 0, 0)
                or color not in {2, 6}
            ):
                raise ValueError("unsupported fixture PNG raster")
            dimensions = width, height, 4 if color == 6 else 3
        elif tag == b"IDAT":
            compressed.extend(data)
        elif tag == b"IEND":
            ended = True
            if end + 4 != len(payload):
                raise ValueError("trailing fixture PNG data")
            break
        cursor = end + 4
    if dimensions is None or not ended:
        raise ValueError("incomplete image fixture PNG")
    width, height, channels = dimensions
    stride = width * channels
    expected = height * (stride + 1)
    if expected > 64 * 1024 * 1024:
        raise ValueError("fixture PNG decoded allocation exceeded")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, expected + 1)
    if (
        len(raw) != expected
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise ValueError("fixture PNG decoded byte count mismatch")
    previous, result = bytearray(stride), []
    for offset in range(0, expected, stride + 1):
        kind = raw[offset]
        row = bytearray(raw[offset + 1 : offset + stride + 1])
        if kind not in range(5):
            raise ValueError("unsupported PNG row filter")
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if kind == 1:
                predictor = left
            elif kind == 2:
                predictor = above
            elif kind == 3:
                predictor = (left + above) // 2
            elif kind == 4:
                base = left + above - upper_left
                distances = abs(base - left), abs(base - above), abs(base - upper_left)
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                predictor = 0
            row[index] = (row[index] + predictor) & 255
        if channels == 4:
            result.extend(row)
        else:
            for index in range(0, stride, 3):
                result.extend((*row[index : index + 3], 255))
        previous = row
    return width, height, result


def validate_artifact(value: Any) -> None:
    """Require actual encoded bytes, digest, dimensions, and independent pixels."""
    if not isinstance(value, dict) or value.get("class") != "PixelArtifact":
        raise ValueError("missing actual PixelArtifact snapshot")
    try:
        if not isinstance(value["bytes"], list) or any(
            type(byte) is not int or not 0 <= byte <= 255 for byte in value["bytes"]
        ):
            raise ValueError("image fixture bytes must be octets")
        payload = bytes(value["bytes"])
        info = value["info"]
        if info["media_type"] == "image/png":
            width, height, rgba = rgba_png(payload)
        elif info["media_type"] == "image/jpeg":
            width, height = jpeg_dimensions(payload)
            # The runner obtains these pixels via an actual public PNG crop.
            # JPEG decoding is owned by the native SDK on both sides.
            rgba = value["rgba"]
            if (
                not isinstance(rgba, list)
                or len(rgba) != width * height * 4
                or any(type(byte) is not int or not 0 <= byte <= 255 for byte in rgba)
            ):
                raise ValueError("invalid decoded JPEG pixel snapshot")
        else:
            raise ValueError("unsupported image fixture format")
        valid = (
            value["width"] == info["width"] == width
            and value["height"] == info["height"] == height
            and value["rgba"] == rgba
            and info["sha256"] == hashlib.sha256(payload).hexdigest()
            and value["metadata"]["sha256"] == info["sha256"]
            and isinstance(info["identity"], str)
            and bool(info["identity"])
        )
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("incomplete actual pixel snapshot") from error
    if not valid:
        raise ValueError("Rust artifact differs from actual PNG pixels or digest")


def jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    """Read bounded JPEG frame dimensions without substituting a Python decoder."""
    if not payload.startswith(b"\xff\xd8\xff") or len(payload) > 8 * 1024 * 1024:
        raise ValueError("invalid bounded JPEG fixture")
    cursor = 2
    while cursor + 4 <= len(payload):
        if payload[cursor] != 255:
            raise ValueError("invalid JPEG fixture marker")
        marker = payload[cursor + 1]
        cursor += 2
        if marker == 255:
            cursor -= 1
            continue
        length = int.from_bytes(payload[cursor : cursor + 2], "big")
        if length < 2 or cursor + length > len(payload):
            raise ValueError("truncated JPEG fixture segment")
        if marker in {0xC0, 0xC1, 0xC2}:
            if length < 8 or payload[cursor + 2] != 8:
                raise ValueError("unsupported JPEG fixture frame")
            height = int.from_bytes(payload[cursor + 3 : cursor + 5], "big")
            width = int.from_bytes(payload[cursor + 5 : cursor + 7], "big")
            if not (0 < width <= 8192 and 0 < height <= 8192):
                raise ValueError("JPEG fixture dimensions exceed bounds")
            return width, height
        if marker in {0xDA, 0xD9}:
            break
        cursor += length
    raise ValueError("JPEG fixture lacks a supported frame")


def _validate_snapshots(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("class") == "PixelArtifact":
            validate_artifact(value)
        elif value.get("class") == "ImageSurface":
            descriptor = value.get("descriptor")
            if (
                not isinstance(descriptor, dict)
                or descriptor.get("controllable") is not False
            ):
                raise ValueError("image reader must have no control authority")
            capabilities = descriptor.get("capabilities", [])
            if {item.get("id") for item in capabilities} != {
                f"image.{name}@1"
                for name in (
                    "overview",
                    "expand",
                    "inspect",
                    "parent",
                    "direct",
                    "overview_pixels",
                    "resize",
                    "crop",
                )
            }:
                raise ValueError("image reader capabilities differ from the contract")
            if any(
                item.get("access") != "read" or item.get("control_domain") is not None
                for item in capabilities
            ):
                raise ValueError("image reader capability grants control authority")
            validate_artifact(value.get("source_artifact"))
        else:
            for child in value.values():
                _validate_snapshots(child)
    elif isinstance(value, list):
        for child in value:
            _validate_snapshots(child)


def _validate_case_pixels(name: str, value: Any) -> None:
    """Require concrete artifacts at the expected result positions for each call."""
    if name in {
        "decode-direct",
        "direct",
        "overview",
        "overview-fits",
        "resize",
        "jpeg-decode-direct",
        "jpeg-direct",
        "jpeg-overview",
    }:
        validate_artifact(value)
    elif name in {"image-reader", "root-artifact", "jpeg-reader"}:
        if not isinstance(value, dict) or value.get("class") != "ImageSurface":
            raise ValueError("image constructor lacks an observed reader")
        _validate_snapshots(value)
    elif name in {"crop-rect", "crop-reference", "jpeg-crop"}:
        if not isinstance(value, dict):
            raise ValueError("image crop lacks an actual result")
        validate_artifact(value.get("artifact"))
        if value.get("png") != value["artifact"]["bytes"]:
            raise ValueError("crop PNG accessor differs from exact artifact bytes")
    elif name in {"screenshot-root", "video-frame-root"}:
        if not isinstance(value, dict):
            raise ValueError("raster root lacks actual restored pixels")
        _validate_case_pixels("image-reader", value.get("reader"))
        validate_artifact(value.get("direct"))
        validate_artifact(value.get("crop"))
        expected = "browser_screenshot" if name == "screenshot-root" else "video_frame"
        if (
            value["direct"]["info"]["source"].get("kind") != expected
            or value["crop"]["info"]["source"] != value["direct"]["info"]["source"]
        ):
            raise ValueError("raster root source provenance was replaced")
    elif name == "archive-portable":
        if not isinstance(value, dict) or value.get("source_count") != 2:
            raise ValueError("portable Outcome lacks its pixel dependency closure")
        for field in ("restored", "root", "crop"):
            validate_artifact(value.get(field))


def validate_fixture_set(value: Any) -> dict[str, Any]:
    """Reject incomplete, duplicate, malformed, or metadata-only Rust output."""
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or value.get("kind") != FIXTURE_KIND
    ):
        raise ValueError("unsupported Rust image fixture output")
    for field, expected in (("cases", CASE_NAMES), ("errorCases", ERROR_NAMES)):
        rows = value.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid Rust image fixture cases")
        names = [row.get("name") for row in rows]
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("Rust image fixture names differ from the contract")
        for row in rows:
            if (
                not isinstance(row.get("input"), dict)
                or "rust" not in row
                or row.get("rustPath") != f"yosoi::surface::{CASE_METHODS[row['name']]}"
            ):
                raise ValueError("incomplete Rust image fixture case")
            if field == "errorCases" and (
                not isinstance(row["rust"], dict)
                or row["rust"].get("rust_type") != "yosoi::surface::SurfaceError"
                or row["rust"].get("variant")
                not in {"Invalid", "Limit", "WrongCapture"}
                or not isinstance(row["rust"].get("details"), dict)
                or row["rust"].get("source_chain") != []
            ):
                raise ValueError("invalid Rust image error contract")
            _validate_snapshots(row["rust"])
            if field == "cases":
                _validate_case_pixels(row["name"], row["rust"])
    source = value.get("input")
    if not isinstance(source, dict):
        raise ValueError("missing Rust image input")
    width, height, pixels = rgba_png(bytes(source["bytes"]))
    if (width, height) != (8, 4):
        raise ValueError("Rust image fixture must contain the known 8x4 raster")
    for y in range(4):
        for x in range(8):
            expected = {
                (True, True): [255, 0, 0, 255],
                (False, True): [0, 255, 0, 255],
                (True, False): [0, 0, 255, 255],
                (False, False): [255, 255, 0, 255],
            }[x < 4, y < 2]
            if pixels[(y * 8 + x) * 4 : (y * 8 + x + 1) * 4] != expected:
                raise ValueError("Rust source PNG differs from known quadrant pixels")
    if jpeg_dimensions(bytes(source["jpeg"]["bytes"])) != (8, 4):
        raise ValueError("Rust JPEG fixture must contain an 8x4 raster")
    return value


def comparison(
    case: dict[str, Any], observed: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Bind complete observed values and actual invocation arguments to digests."""
    expected, observed = case["rust"], _plain(observed)
    return {
        "name": case["name"],
        "rustPath": case["rustPath"],
        "rust": expected,
        "python": observed,
        "rustSha256": parity.digest_json(expected),
        "pythonSha256": parity.digest_json(observed),
        "equal": expected == observed,
        "comparisons": [
            {
                "name": f"image:{case['name']}:complete-value",
                "rustSha256": parity.digest_json(expected),
                "pythonSha256": parity.digest_json(observed),
                "equal": expected == observed,
            }
        ],
        "mappingValues": {"rust": case["input"], "python": arguments},
    }


def evidence_cases(
    comparisons: list[dict[str, Any]], rust: dict[str, Any], ledger: dict[str, Any]
) -> list[dict[str, Any]]:
    """Attribute only executed declarations with pinned mappings and observations."""
    items = {item["rustPath"]: item for item in rust.get("items", [])}
    entries = {
        entry.get("symbolKey"): entry
        for entry in ledger.get("entries", [])
        if entry.get("decision") == "mapped"
    }
    cases = []
    for observed in comparisons:
        path = observed["rustPath"]
        item = items.get(path)
        entry = entries.get(item.get("symbolKey")) if item else None
        if item is None or entry is None or entry.get("rustPath") != path:
            raise ValueError(f"image conformance lacks a pinned mapping for {path}")
        checks = _mapping_checks(entry, observed["mappingValues"])
        passed = observed["equal"] and all(check["equal"] for check in checks)
        cases.append(
            {
                "testId": f"image-surface:{observed['name']}:{item['symbolKey']}",
                "rustPath": path,
                "symbolKey": item["symbolKey"],
                "pythonTarget": entry["pythonTarget"],
                "outcome": "passed" if passed else "failed",
                "comparisons": observed["comparisons"],
                "mappingChecks": checks,
            }
        )
    return cases
