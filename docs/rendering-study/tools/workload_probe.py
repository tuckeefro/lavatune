"""Count evaluated and emitted cells; these diagnostic passes are not timings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_study import COMMIT, ROOT, SIZES, load_benchmark
from verify_public_sources import verify_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "_sources/lavatune-public")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/main-study/workload.json")
    parser.add_argument("--frames", type=int, default=200)
    options = parser.parse_args()
    if options.frames < 100 or options.frames % 100:
        parser.error("Use complete 100-frame input cycles")
    verify_source(options.source, ROOT / "evidence/public-source-manifest.json")
    bench = load_benchmark(options.source)
    records = []
    for width, height in SIZES:
        scalar = bench.LavaField()
        scalar.resize(max(10, width // 3), height)
        contour = bench.LavaField()
        contour.resize(width, height)
        config = bench.LavaConfig(blobs=4)
        style = bench.MaterialStyle()
        nonblank = 0
        emitted = 0
        bench.FLUID_MATERIAL.reset_cache_metrics()
        for index in range(options.frames):
            frame, mode = bench.synthetic_frame(index)
            scalar._last_step_at = contour._last_step_at = None
            scalar.step(frame, mode, "atlas", 1.0, config)
            for y in range(height):
                for x in range(width):
                    cell = bench.FLUID_MATERIAL.cell(scalar.field_frame, x, y, width, height, style, scalar.phase)
                    nonblank += cell.glyph != " "
            contour.step(frame, mode, "atlas", 1.0, config, rasterize=False, surface_ripples=True)
            spans = bench.FLUID_MATERIAL.render_spans(contour.bodies, contour.forces, width, height, style, contour.phase, 1.85)
            emitted += sum(len(span.cells) for row in spans.values() for span in row)
        hits, misses = bench.FLUID_MATERIAL.cache_metrics()
        records.append({
            "width": width, "height": height, "frames": options.frames,
            "scalar_cell_evaluations": width * height * options.frames,
            "scalar_nonblank_cells": nonblank,
            "scalar_blank_fraction": 1 - nonblank / (width * height * options.frames),
            "contour_emitted_cells": emitted,
            "contour_mean_emitted_cells_per_frame": emitted / options.frames,
            "contour_cache_hits": hits, "contour_cache_misses": misses,
        })
    report = {
        "source_commit": COMMIT,
        "scope": "Separate diagnostic replay; emitted cells do not count every internal contour evaluation, and the two outputs are not equivalent.",
        "results": records,
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
