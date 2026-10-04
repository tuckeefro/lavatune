"""Draw the recorded benchmark as PNG, SVG, and PDF using Pycairo."""
from __future__ import annotations

import json
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1600, 1000
INK = (0.10, 0.15, 0.19)
GRAY = (0.33, 0.39, 0.45)
TEAL = (0.00, 0.39, 0.37)
BACKGROUND = (0.97, 0.96, 0.93)


def label(ctx, value, x, y, size=28, color=INK, bold=False):
    ctx.set_source_rgb(*color)
    ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)
    ctx.move_to(x, y)
    ctx.show_text(value)


def draw(surface, report):
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(*BACKGROUND)
    ctx.paint()
    label(ctx, "Rendering less in a Python visualizer", 80, 91, 52, bold=True)
    label(ctx, "Measured compute time per simulated frame", 80, 143, 32)
    for x, color, title in ((80, GRAY, "Scalar field + every terminal cell"), (770, TEAL, "Analytic contour spans")):
        ctx.set_source_rgb(*color)
        ctx.rectangle(x, 179, 26, 26)
        ctx.fill()
        label(ctx, title, x + 42, 203, 28)
    plot_left, plot_right = 290, 1370
    scale = (plot_right - plot_left) / 50
    for tick in range(0, 51, 10):
        x = plot_left + tick * scale
        ctx.set_source_rgb(0.82, 0.83, 0.81)
        ctx.set_line_width(1)
        ctx.move_to(x, 250)
        ctx.line_to(x, 745)
        ctx.stroke()
        label(ctx, str(tick), x - 12, 788, 26, GRAY)
    label(ctx, "milliseconds · lower is better", 815, 829, 28, GRAY)
    for index, result in enumerate(report["results"]):
        top = 269 + index * 165
        label(ctx, f"{result['width']} × {result['height']}", 80, top + 38, 33, bold=True)
        label(ctx, f"{result['cells']:,} cells", 80, top + 76, 25, GRAY)
        for offset, method, color in ((0, "scalar_field", GRAY), (60, "analytic_contour", TEAL)):
            values = result["methods"][method]
            median = values["median_ms_per_frame"]
            y = top + offset
            ctx.set_source_rgb(*color)
            ctx.rectangle(plot_left, y, median * scale, 36)
            ctx.fill()
            low = plot_left + values["min_ms_per_frame"] * scale
            high = plot_left + values["max_ms_per_frame"] * scale
            center_y = y + 18
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(3)
            ctx.move_to(low, center_y)
            ctx.line_to(high, center_y)
            ctx.move_to(low, center_y - 8)
            ctx.line_to(low, center_y + 8)
            ctx.move_to(high, center_y - 8)
            ctx.line_to(high, center_y + 8)
            ctx.stroke()
            label(ctx, f"{median:.2f}", max(high, plot_left + median * scale) + 16, y + 29, 29, color, bold=True)
    label(ctx, "Bars: median of 5 run averages. Whiskers: min–max across those 5 runs.", 80, 887, 26)
    label(ctx, "200 synthetic feature frames/run · Python 3.13.5 · Intel i5-4570 · Linux", 80, 929, 25, GRAY)
    label(ctx, "Different visual representations. Excludes live capture and terminal output. 2026-10-04.", 80, 969, 24, GRAY)


def main():
    report = json.loads((ROOT / "evidence/main-study/benchmark-summary.json").read_text())
    output = ROOT / "publication"
    output.mkdir(exist_ok=True)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    draw(surface, report)
    surface.write_to_png(str(output / "figure.png"))
    for kind, constructor in (("svg", cairo.SVGSurface), ("pdf", cairo.PDFSurface)):
        with constructor(str(output / f"figure.{kind}"), WIDTH, HEIGHT) as surface:
            draw(surface, report)
    print(json.dumps({"figure": "publication/figure.png", "width": WIDTH, "height": HEIGHT}))


if __name__ == "__main__":
    main()
