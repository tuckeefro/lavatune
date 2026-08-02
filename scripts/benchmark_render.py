#!/usr/bin/env python3
"""Compare the alpha scalar-field Fluid path with the low-power contour path."""

from __future__ import annotations

import argparse
import json
import platform
import time

from benchmark import synthetic_frame
from lavatune.app import LavaField
from lavatune.config import LavaConfig
from lavatune.materials import FLUID_MATERIAL, TEXT_MATERIAL, MaterialStyle


def _measure_alpha_path(width: int, height: int, frames: int) -> float:
    field = LavaField()
    field.resize(max(10, width // 3), height)
    config = LavaConfig(blobs=4)
    style = MaterialStyle()
    started = time.perf_counter()
    for index in range(frames):
        frame, mode = synthetic_frame(index)
        field._last_step_at = None
        field.step(frame, mode, "atlas", 1.0, config)
        for y in range(height):
            for x in range(width):
                FLUID_MATERIAL.cell(
                    field.field_frame,
                    x,
                    y,
                    width,
                    height,
                    style,
                    field.phase,
                )
    return (time.perf_counter() - started) * 1000.0 / frames


def _measure_contour_path(width: int, height: int, frames: int) -> tuple[float, float]:
    field = LavaField()
    field.resize(width, height)
    config = LavaConfig(blobs=4)
    style = MaterialStyle()
    FLUID_MATERIAL.reset_cache_metrics()
    started = time.perf_counter()
    for index in range(frames):
        frame, mode = synthetic_frame(index)
        field._last_step_at = None
        field.step(frame, mode, "atlas", 1.0, config, rasterize=False)
        FLUID_MATERIAL.render_spans(
            field.bodies,
            field.forces,
            width,
            height,
            style,
            field.phase,
            1.85,
        )
    milliseconds = (time.perf_counter() - started) * 1000.0 / frames
    hits, misses = FLUID_MATERIAL.cache_metrics()
    return milliseconds, hits / max(1, hits + misses)


def _measure_cached_contour(width: int, height: int, frames: int) -> float:
    field = LavaField()
    field.resize(width, height)
    style = MaterialStyle()
    frame, mode = synthetic_frame(65)
    field.step(frame, mode, "atlas", 1.0, LavaConfig(blobs=4), rasterize=False)
    FLUID_MATERIAL.render_spans(
        field.bodies, field.render_forces, width, height, style, field.phase, 1.85
    )
    started = time.perf_counter()
    for _ in range(frames):
        FLUID_MATERIAL.render_spans(
            field.bodies, field.render_forces, width, height, style, field.phase, 1.85
        )
    return (time.perf_counter() - started) * 1000.0 / frames


def _measure_text_path(width: int, height: int, frames: int) -> float:
    field = LavaField()
    field.resize(max(10, width // 3), height)
    config = LavaConfig(blobs=4)
    style = MaterialStyle()
    started = time.perf_counter()
    for index in range(frames):
        frame, mode = synthetic_frame(index)
        field._last_step_at = None
        field.step(frame, mode, "atlas", 1.0, config)
        TEXT_MATERIAL.render(
            field.field_frame,
            width,
            height,
            style,
            field.phase,
        )
    return (time.perf_counter() - started) * 1000.0 / frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--width", type=int, default=120)
    parser.add_argument("--height", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    frames = max(1, args.frames)
    width = max(10, args.width)
    height = max(6, args.height)

    alpha_ms = _measure_alpha_path(width, height, frames)
    contour_ms, contour_cache_rate = _measure_contour_path(width, height, frames)
    cached_ms = _measure_cached_contour(width, height, frames)
    text_ms = _measure_text_path(width, height, frames)
    report = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "width": width,
        "height": height,
        "frames": frames,
        "alpha_ms_per_frame": round(alpha_ms, 3),
        "contour_ms_per_frame": round(contour_ms, 3),
        "cached_contour_ms_per_frame": round(cached_ms, 3),
        "contour_cache_rate": round(contour_cache_rate, 3),
        "text_ms_per_frame": round(text_ms, 3),
        "speedup": round(alpha_ms / max(0.001, contour_ms), 2),
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"Python {report['python']} on {report['machine']} | {width}x{height}")
        print(f"alpha field + Fluid  {alpha_ms:7.3f} ms/frame")
        print(f"contour Fluid        {contour_ms:7.3f} ms/frame")
        print(f"cached contour       {cached_ms:7.3f} ms/frame")
        print(f"sequence cache rate  {contour_cache_rate * 100:7.1f}%")
        print(f"prepared Text        {text_ms:7.3f} ms/frame")
        print(f"speedup              {report['speedup']:7.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
