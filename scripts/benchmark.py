#!/usr/bin/env python3
"""Measure the deterministic audio-to-terminal field pipeline without live capture."""

from __future__ import annotations

import argparse
import json
import math
import platform
import resource
import time

from lavatune.app import LavaField
from lavatune.audio import AudioFrame
from lavatune.config import LavaConfig


SHAPES = {
    "micro": (18, 8),
    "chimney": (20, 32),
    "basin": (44, 18),
    "current": (90, 12),
}


def synthetic_frame(index: int) -> tuple[AudioFrame, str]:
    phase = (index % 100) / 22.0
    section = (index // 20) % 5
    if section == 0:
        return AudioFrame(0.0, [0.0] * 8, 0.0, 0.0, phase), "book"
    if section == 1:
        syllable = 0.5 + 0.5 * math.sin(phase * 5.2)
        return AudioFrame(
            0.14 + syllable * 0.16,
            [0.08, 0.14, 0.36, 0.58, 0.44, 0.20, 0.08, 0.04],
            syllable * 0.08,
            0.08,
            phase,
        ), "speech"
    if section == 2:
        beat = max(0.0, math.sin(phase * 6.0)) ** 7
        return AudioFrame(
            0.26 + beat * 0.30,
            [0.72 + beat * 0.25, 0.62, 0.32, 0.15, 0.08, 0.04, 0.02, 0.01],
            beat * 0.30,
            0.04,
            phase,
        ), "music"
    if section == 3:
        beat = max(0.0, math.sin(phase * 7.4)) ** 6
        return AudioFrame(
            0.30 + beat * 0.22,
            [0.52 + beat * 0.24, 0.46, 0.34, 0.42, 0.38, 0.28, 0.22, 0.16],
            beat * 0.28,
            0.13,
            phase,
        ), "music"
    strike = 0.92 if index % 10 == 0 else 0.04
    return AudioFrame(
        0.18 + strike * 0.45,
        [0.18, 0.22, 0.30, 0.42, 0.56, 0.70, 0.88, 0.80],
        strike,
        0.22,
        phase,
    ), "music"


def benchmark_shape(name: str, width: int, height: int, frames: int) -> dict[str, object]:
    field = LavaField()
    field.resize(width, height)
    config = LavaConfig(blobs=6)
    for index in range(12):
        frame, mode = synthetic_frame(index)
        field._last_step_at = None
        field.step(frame, mode, "atlas", 1.0, config)

    started = time.perf_counter()
    for index in range(frames):
        frame, mode = synthetic_frame(index)
        field._last_step_at = None
        field.step(frame, mode, "atlas", 1.0, config)
    elapsed = time.perf_counter() - started
    milliseconds = elapsed * 1000.0 / frames
    return {
        "shape": name,
        "cells": width * height,
        "frames": frames,
        "ms_per_frame": round(milliseconds, 3),
        "pipeline_fps": round(1000.0 / milliseconds, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=250)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    frames = max(1, min(5000, args.frames))
    results = [benchmark_shape(name, width, height, frames) for name, (width, height) in SHAPES.items()]
    report = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "results": results,
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
        return 0
    print(f"Python {report['python']} on {report['machine']} | max RSS {report['max_rss_kib']} KiB")
    for result in results:
        print(
            f"{result['shape']:8} {result['cells']:4} cells  "
            f"{result['ms_per_frame']:7.3f} ms/frame  "
            f"{result['pipeline_fps']:7.1f} pipeline fps"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
