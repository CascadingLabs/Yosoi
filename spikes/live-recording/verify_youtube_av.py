"""Verify actual YouTube per-tab A/V and reciprocal pause-window audio leakage."""

import argparse
import array
import hashlib
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


def rms(samples, start, end, rate=48000):
    segment = samples[
        max(0, round(start * rate)) : min(len(samples), round(end * rate))
    ]
    if not segment:
        raise RuntimeError("Empty measurement window")
    return math.sqrt(sum(value * value for value in segment) / len(segment))


def db(value):
    return None if value == 0 else round(20 * math.log10(value), 2)


def verify(root, *, transcode=True):
    report = json.loads((root / "browser-report.json").read_text())
    if report.get("mode") != "youtube" or report["tabs"] != 2:
        raise RuntimeError("Two actual YouTube sources are required")
    processes = json.loads((root / "owned-processes.json").read_text())
    browsers = [
        process
        for process in processes
        if process["argv"]
        and process["argv"][0].endswith("/chrome")
        and not any(arg.startswith("--type=") for arg in process["argv"])
    ]
    if len(browsers) != 1:
        raise RuntimeError("Expected one Chrome browser process")
    for item in report["isolation"]:
        if (
            item["initial_state"]["storage"] is not None
            or item["initial_state"]["cookie"]
        ):
            raise RuntimeError("Fresh context exposed another context state")
    devices = [item["video"]["deviceId"] for item in report["ready"]]
    if len(set(devices)) != 2:
        raise RuntimeError("Both captures resolve to the same WebContents source")
    media, audio_samples, visual_samples = [], [], []
    for index, metadata in enumerate(report["results"]):
        source = root / f"tab-{index}.webm"
        if source.stat().st_size != metadata["bytes"]:
            raise RuntimeError("Exported bytes differ from MediaRecorder output")
        info = json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=index,codec_type,codec_name,width,height,sample_rate,channels",
                    "-of",
                    "json",
                    str(source),
                ]
            )
        )
        if {stream["codec_type"] for stream in info["streams"]} != {"audio", "video"}:
            raise RuntimeError("A/V tracks missing")
        timing = json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "frame=best_effort_timestamp_time,width,height",
                    "-of",
                    "json",
                    str(source),
                ]
            )
        )["frames"]
        times = [float(frame["best_effort_timestamp_time"]) for frame in timing]
        gaps = [after - before for before, after in zip(times, times[1:], strict=False)]
        if not gaps or min(gaps) <= 0 or times[-1] < 24:
            raise RuntimeError("Incomplete or non-monotonic video")
        pictures = run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-threads",
                "1",
                "-filter_threads",
                "1",
                "-i",
                str(source),
                "-an",
                "-vf",
                "scale=32:18:flags=area,format=gray",
                "-fps_mode",
                "passthrough",
                "-threads",
                "1",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        stride = 32 * 18
        if len(pictures) != len(times) * stride:
            raise RuntimeError("Decoded picture count differs from timestamps")
        unique = len(
            {
                hashlib.sha256(pictures[start : start + stride]).digest()
                for start in range(0, len(pictures), stride)
            }
        )
        if unique < 100:
            raise RuntimeError("Too little actual movie motion")
        sample = min(range(len(times)), key=lambda offset: abs(times[offset] - 3))
        visual_samples.append(pictures[sample * stride : (sample + 1) * stride])
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
        if len(pcm) < 48000 * 24:
            raise RuntimeError("Incomplete audio")
        audio_samples.append(pcm)
        dimensions = sorted({(frame["width"], frame["height"]) for frame in timing})
        media.append(
            {
                "id": index,
                "title": metadata["source"]["title"],
                "url": metadata["source"]["url"],
                "capture": metadata["source"]["crop"],
                "streams": info["streams"],
                "frames": len(times),
                "unique_movie_frames": unique,
                "dimensions": dimensions,
                "first_video_pts": times[0],
                "last_video_pts": times[-1],
                "median_video_interval_ms": round(statistics.median(gaps) * 1000, 2),
                "maximum_video_gap_ms": round(max(gaps) * 1000, 2),
                "audio_seconds": round(len(pcm) / 48000, 3),
                "initial_audio_rms_dbfs": db(rms(pcm, 1, 5)),
            }
        )
        if transcode:
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-n",
                    "-threads",
                    "1",
                    "-filter_threads",
                    "1",
                    "-i",
                    str(source),
                    "-vf",
                    "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
                    "-c:v",
                    "libx264",
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
                    "128k",
                    "-movflags",
                    "+faststart",
                    "-metadata",
                    f"title={metadata['source']['title']}",
                    "-metadata",
                    "artist=Blender Foundation",
                    "-metadata",
                    f"comment=Recorded from {metadata['source']['url']}; "
                    "source film by Blender Foundation",
                    str(root / f"tab-{index}.mp4"),
                ]
            )
    picture_difference = sum(
        abs(a - b) for a, b in zip(*visual_samples, strict=True)
    ) / len(visual_samples[0])
    if picture_difference < 3:
        raise RuntimeError("Captured pictures are unexpectedly similar")
    checks = []
    for index in range(2):
        pause = next(
            phase
            for phase in report["phases"]
            if phase["id"] == index and phase["action"] == "pause"
        )
        resume = next(
            phase
            for phase in report["phases"]
            if phase["id"] == index and phase["action"] == "resume"
        )
        start = pause["observed"]["at"] + 800
        end = resume["observed"]["at"] - 500
        own = report["results"][index]["startedAt"]
        other = report["results"][1 - index]["startedAt"]
        quiet = rms(audio_samples[index], (start - own) / 1000, (end - own) / 1000)
        active = rms(
            audio_samples[1 - index], (start - other) / 1000, (end - other) / 1000
        )
        rejection = None if quiet == 0 else 20 * math.log10(max(active, 1e-12) / quiet)
        passed = (
            active > 0.003 and quiet < 0.0003 and (rejection is None or rejection > 35)
        )
        checks.append(
            {
                "paused_tab": index,
                "active_tab": 1 - index,
                "absolute_window_ms": [start, end],
                "paused_audio_dbfs": db(quiet),
                "other_tab_audio_dbfs": db(active),
                "separation_db": None if rejection is None else round(rejection, 2),
                "digital_silence": quiet == 0,
                "passed": passed,
            }
        )
    summary = {
        "browser_processes": 1,
        "isolated_contexts": 2,
        "distinct_webcontents_sources": True,
        "video_difference_mean_gray": round(picture_difference, 2),
        "media": media,
        "audio_bleed_checks": checks,
        "no_bleed_observed": all(check["passed"] for check in checks),
        "conditions": json.loads((root / "conditions.json").read_text()),
        "limits": (
            "Two chosen real videos and reciprocal pause windows; "
            "not a universal process-security or arbitrary-site guarantee. "
            "MP4 conversion preserves timing and letterboxes capture resize."
        ),
    }
    (root / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not summary["no_bleed_observed"]:
        raise RuntimeError(
            "Leakage test failed or the other source was too quiet to qualify"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--no-transcode",
        action="store_true",
        help="Verify existing recordings without rewriting MP4s",
    )
    args = parser.parse_args()
    verify(args.output, transcode=not args.no_transcode)
