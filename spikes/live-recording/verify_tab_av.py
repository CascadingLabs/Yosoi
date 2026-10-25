"""Decode per-tab browser recordings and measure video, isolated audio and overlap."""

import argparse
import array
import json
import math
import statistics
import subprocess
from pathlib import Path


def run(command):
    result = subprocess.run(command, capture_output=True, check=True)
    if result.stderr:
        raise RuntimeError(result.stderr.decode())
    return result.stdout


def power(samples, frequency, rate):
    coefficient = 2 * math.cos(2 * math.pi * frequency / rate)
    previous = before = 0.0
    for sample in samples:
        current = sample + coefficient * previous - before
        before, previous = previous, current
    return max(
        0, previous * previous + before * before - coefficient * previous * before
    )


def verify(root, *, transcode=True):
    report = json.loads((root / "browser-report.json").read_text())
    count = report["tabs"]
    frequencies = [440 * (index + 1) for index in range(count)]
    owned = json.loads((root / "owned-processes.json").read_text())
    browsers = [
        process
        for process in owned
        if process["argv"]
        and process["argv"][0].endswith("/chrome")
        and not any(argument.startswith("--type=") for argument in process["argv"])
    ]
    if len(browsers) != 1:
        raise RuntimeError(f"Expected one Chrome browser, got {browsers}")
    if any(
        "chromedriver" in argument.lower()
        for process in owned
        for argument in process["argv"]
    ):
        raise RuntimeError("Unexpected ChromeDriver")
    results = []
    for index in range(count):
        metadata = json.loads((root / f"tab-{index}.json").read_text())
        source = root / f"tab-{index}.webm"
        info = json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=index,codec_name,codec_type,width,height,sample_rate,channels",
                    "-of",
                    "json",
                    str(source),
                ]
            )
        )
        video = next(
            stream for stream in info["streams"] if stream["codec_type"] == "video"
        )
        audio = next(
            stream for stream in info["streams"] if stream["codec_type"] == "audio"
        )
        if not (0 < video["width"] <= 640 and 0 < video["height"] <= 360):
            raise RuntimeError(f"Unexpected fixture geometry: {video}")
        frames = json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "frame=best_effort_timestamp_time",
                    "-of",
                    "json",
                    str(source),
                ]
            )
        )["frames"]
        timestamps = [float(frame["best_effort_timestamp_time"]) for frame in frames]
        gaps = [
            after - before
            for before, after in zip(timestamps, timestamps[1:], strict=False)
        ]
        if not gaps or min(gaps) <= 0:
            raise RuntimeError("Missing or non-monotonic video timestamps")
        header = run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-threads",
                "1",
                "-i",
                str(source),
                "-an",
                "-vf",
                "scale=960:-2,crop=640:80:0:0,format=gray",
                "-fps_mode",
                "passthrough",
                "-threads",
                "1",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        stride = 640 * 80
        if len(header) != stride * len(timestamps):
            raise RuntimeError("Decoded frame count mismatch")
        counters, flash = [], []
        for frame_index in range(len(timestamps)):
            offset = frame_index * stride
            value = sum(
                (header[offset + 70 * 640 + 14 + bit * 12] > 128) << bit
                for bit in range(16)
            )
            counters.append(value)
            flash.append(header[offset + 40 * 640 + 600] > 128)
        pcm = array.array("f")
        pcm.frombytes(
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-f",
                    "f32le",
                    "-",
                ]
            )
        )
        if len(pcm) < 48000 * 12:
            raise RuntimeError("Audio did not continue through the capture")
        window_size = 9600
        windows = [
            pcm[start : start + window_size]
            for start in range(0, len(pcm) - window_size, window_size)
        ]
        loudest = max(
            windows, key=lambda window: sum(value * value for value in window)
        )
        rms = math.sqrt(sum(value * value for value in loudest) / len(loudest))
        powers = {
            frequency: power(loudest, frequency, 48000) for frequency in frequencies
        }
        expected = frequencies[index]
        others = [value for frequency, value in powers.items() if frequency != expected]
        separation = 10 * math.log10(
            max(powers[expected], 1e-12) / max(max(others), 1e-12)
        )
        if rms < 0.01 or separation < 15:
            raise RuntimeError(
                f"Missing or mixed tab audio: RMS={rms}, separation={separation} dB"
            )
        envelope = []
        for start in range(0, len(pcm) - 480, 480):
            segment = pcm[start : start + 480]
            envelope.append(math.sqrt(sum(value * value for value in segment) / 480))
        threshold = max(envelope) * 0.5
        alignment = []
        for shift in range(-25, 26):
            observed = []
            for timestamp, bright in zip(timestamps, flash, strict=True):
                audio_bin = round((timestamp + shift / 100) * 100)
                if 100 < audio_bin < len(envelope) - 100:
                    observed.append(bright == (envelope[audio_bin] > threshold))
            if observed:
                alignment.append((sum(observed) / len(observed), shift))
        score, shift = max(alignment)
        video_duration = timestamps[-1] - timestamps[0] + statistics.median(gaps)
        unique = len(set(counters))
        if unique < 100 or timestamps[-1] < 12:
            raise RuntimeError(
                f"Video froze or was too short: {unique} unique counters"
            )
        if metadata["stoppedAt"] - metadata["startedAt"] < 15000:
            raise RuntimeError("MediaRecorder stopped before the requested interval")
        result = {
            "id": index,
            "frequency_hz": expected,
            "codecs": [video["codec_name"], audio["codec_name"]],
            "frames": len(timestamps),
            "unique_frame_counters": unique,
            "video_seconds": round(video_duration, 3),
            "decoded_fps": round(len(timestamps) / video_duration, 2),
            "unique_fps": round(unique / video_duration, 2),
            "largest_frame_gap_ms": round(max(gaps) * 1000, 2),
            "audio_seconds": round(len(pcm) / 48000, 3),
            "audio_rms": round(rms, 4),
            "own_tone_vs_other_tabs_db": round(separation, 2),
            "pulse_av_offset_estimate_ms": shift * 10 if score >= 0.9 else None,
            "pulse_alignment_qualified": score >= 0.9,
            "pulse_match_fraction": round(score, 3),
            "focus_at_stop": metadata["focusAtStop"],
            "visibility_at_stop": metadata["visibilityAtStop"],
        }
        results.append(result)
        if transcode:
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-n",
                    "-threads",
                    "1",
                    "-i",
                    str(source),
                    "-c:v",
                    "libx264",
                    "-vf",
                    "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
                    "-threads",
                    "1",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-fps_mode",
                    "passthrough",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    "-movflags",
                    "+faststart",
                    str(root / f"tab-{index}.mp4"),
                ]
            )
    starts = [item["startedAt"] for item in report["results"]]
    stops = [item["stoppedAt"] for item in report["results"]]
    overlap = (min(stops) - max(starts)) / 1000
    background = (min(stops) - report["control_before"]["at"]) / 1000
    if overlap < 5 or background < 5:
        raise RuntimeError("Insufficient simultaneous background recording interval")
    output = {
        "tabs": count,
        "browser_processes": len(browsers),
        "shared_window": True,
        "concurrent_overlap_seconds": round(overlap, 3),
        "all_sources_background_seconds": round(background, 3),
        "conditions": json.loads((root / "conditions.json").read_text()),
        "results": results,
        "limits": (
            "Cooperating self-capture fixtures with an isolated test capture grant. "
            "Pulse offset is a heuristic, not calibrated end-to-end latency."
        ),
    }
    (root / "verification.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--no-transcode", action="store_true")
    args = parser.parse_args()
    verify(args.output, transcode=not args.no_transcode)
