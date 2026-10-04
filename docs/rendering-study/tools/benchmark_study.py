"""Collect repeated, counterbalanced compute-path timings into CSV and SQLite."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import platform
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from verify_public_sources import verify_source

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "f79516e82b9b6383ea1d169be2937c9ba6a5a93d"
SIZES = ((60, 18), (90, 24), (120, 30))
SCHEMA = """
CREATE TABLE benchmark_runs (
    source_commit TEXT NOT NULL,
    width INTEGER NOT NULL CHECK(width > 0),
    height INTEGER NOT NULL CHECK(height > 0),
    repeat INTEGER NOT NULL CHECK(repeat >= 0),
    method TEXT NOT NULL CHECK(method IN ('scalar_field', 'analytic_contour')),
    frames INTEGER NOT NULL CHECK(frames >= 100),
    execution_order INTEGER NOT NULL CHECK(execution_order IN (0, 1)),
    ms_per_frame REAL NOT NULL CHECK(ms_per_frame > 0),
    PRIMARY KEY (source_commit, width, height, repeat, method)
);
"""


def load_benchmark(source: Path):
    sys.path.insert(0, str(source / "src"))
    sys.path.insert(0, str(source / "scripts"))
    specification = importlib.util.spec_from_file_location("render_benchmark", source / "scripts/benchmark_render.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def validate_rows(rows: list[dict], frames: int, repeats: int) -> None:
    """Require a complete paired design, valid times, and declared source identity."""
    expected = {(w, h, r, method) for w, h in SIZES for r in range(repeats)
                for method in ("scalar_field", "analytic_contour")}
    observed = set()
    for row in rows:
        key = (row["width"], row["height"], row["repeat"], row["method"])
        if key in observed or key not in expected:
            raise ValueError("Duplicate or unexpected benchmark observation")
        if row["source_commit"] != COMMIT or row["frames"] != frames:
            raise ValueError("Benchmark source or frame count differs from the protocol")
        if not math.isfinite(row["ms_per_frame"]) or row["ms_per_frame"] <= 0:
            raise ValueError("Timing must be finite and positive")
        expected_order = int(row["method"] == "analytic_contour") ^ (row["repeat"] % 2)
        if row["execution_order"] != expected_order:
            raise ValueError("Execution order differs from the alternating protocol")
        observed.add(key)
    if observed != expected:
        raise ValueError("Benchmark design is incomplete")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "_sources/lavatune-public")
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/main-study")
    parser.add_argument("--manifest", type=Path, default=ROOT / "evidence/public-source-manifest.json")
    options = parser.parse_args()
    if options.frames < 100 or options.frames % 100 or options.repeats < 3:
        parser.error("Use whole 100-frame input cycles and at least three repeats")
    source_receipt = verify_source(options.source, options.manifest)
    bench = load_benchmark(options.source)
    evidence = options.output
    evidence.mkdir(parents=True, exist_ok=True)
    for filename in ("benchmark-runs.csv", "benchmark.sqlite", "benchmark-summary.json"):
        if (evidence / filename).exists():
            parser.error("The output already contains results; use a new --output directory")
    methods = {
        "scalar_field": bench._measure_alpha_path,
        "analytic_contour": lambda width, height, frames: bench._measure_contour_path(width, height, frames)[0],
    }
    rows = []
    started = datetime.now(timezone.utc).isoformat()
    for width, height in SIZES:
        for method in methods.values():
            method(width, height, 20)
        for repeat in range(options.repeats):
            ordered = list(methods)
            if repeat % 2:
                ordered.reverse()
            for order, method in enumerate(ordered):
                elapsed = methods[method](width, height, options.frames)
                row = {"source_commit": COMMIT, "width": width, "height": height, "repeat": repeat, "method": method, "frames": options.frames, "execution_order": order, "ms_per_frame": elapsed}
                rows.append(row)
                print(json.dumps(row), flush=True)
    validate_rows(rows, options.frames, options.repeats)
    csv_path = evidence / "benchmark-runs.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    database = evidence / "benchmark.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO benchmark_runs VALUES (:source_commit,:width,:height,:repeat,:method,:frames,:execution_order,:ms_per_frame)", rows)
        connection.execute("CREATE VIEW benchmark_means AS SELECT width,height,method,COUNT(*) AS repeats,AVG(ms_per_frame) AS mean_ms,MIN(ms_per_frame) AS min_ms,MAX(ms_per_frame) AS max_ms FROM benchmark_runs GROUP BY width,height,method")
    summaries = []
    for width, height in SIZES:
        values = {method: [row["ms_per_frame"] for row in rows if row["width"] == width and row["height"] == height and row["method"] == method] for method in methods}
        medians = {method: statistics.median(times) for method, times in values.items()}
        summaries.append({"width": width, "height": height, "cells": width * height, "methods": {method: {"median_ms_per_frame": medians[method], "min_ms_per_frame": min(times), "max_ms_per_frame": max(times)} for method, times in values.items()}, "ratio_of_run_medians": medians["scalar_field"] / medians["analytic_contour"]})
    cpu_info = Path("/proc/cpuinfo")
    cpu = next((line.split(":", 1)[1].strip() for line in cpu_info.read_text().splitlines() if line.startswith("model name")), "unavailable") if cpu_info.exists() else platform.processor() or "unavailable"
    report = {
        "source_commit": COMMIT, "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": platform.python_version(), "architecture": platform.machine(), "system": platform.system(), "cpu": cpu},
        "source_verification": source_receipt,
        "frames_per_run": options.frames, "repeats_per_method_per_size": options.repeats, "recorded_runs": len(rows),
        "warmup": "20 unrecorded frames using a separate field instance for each method at each size; warms the interpreter, not the recorded simulation",
        "order": "Alternating path order across repeats; viewport sizes run in ascending order",
        "statistic": f"Median of {options.repeats} run-average wall-clock times per simulated frame; not frame-level latency percentiles",
        "input": f"{options.frames // 100} complete repetitions of the existing 100-frame synthetic feature sequence; no PCM decoding",
        "raw_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "excluded": ["live PCM capture", "curses writes", "terminal emulator", "compositor", "power measurement"],
        "comparison_boundary": "Two existing rendering strategies with different field representations; not a pixel-equivalent microbenchmark",
        "results": summaries,
    }
    (evidence / "benchmark-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"completed_runs": len(rows), "summaries": summaries}), flush=True)


if __name__ == "__main__":
    main()
