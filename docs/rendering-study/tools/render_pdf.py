"""Typeset the article directly with Cairo; no browser or network is needed."""
from __future__ import annotations

import re
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parents[1]
PAGE_WIDTH, PAGE_HEIGHT = 595.28, 841.89
MARGIN = 54
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN
INK = (0.10, 0.15, 0.19)
MUTED = (0.33, 0.39, 0.43)
TEAL = (0.00, 0.39, 0.37)
WEB = "https://github.com/tuckeefro/lavatune/blob/docs/rendering-evidence-2026-10/docs/rendering-study/publication/"


def fragments(text):
    pattern = re.compile(r"\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)")
    start = 0
    output = []
    for match in pattern.finditer(text):
        if match.start() > start:
            output.append((text[start:match.start()], False, False, None))
        bold, code, linked, target = match.groups()
        if target and target.endswith(".md") and ":" not in target:
            target = WEB + target
        output.append((bold or code or linked, bool(bold), bool(code), target))
        start = match.end()
    if start < len(text):
        output.append((text[start:], False, False, None))
    return output


class Document:
    def __init__(self):
        self.pages = []
        self.new_page()

    def new_page(self):
        if hasattr(self, "ctx"):
            self.finish_page()
        self.surface = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, (0, 0, PAGE_WIDTH, PAGE_HEIGHT))
        self.ctx = cairo.Context(self.surface)
        self.ctx.set_source_rgb(1, 1, 1)
        self.ctx.paint()
        self.y = MARGIN
        if self.pages:
            self.font(9, color=MUTED)
            self.ctx.move_to(MARGIN, 32)
            self.ctx.show_text("Rendering less in a Python visualizer")

    def finish_page(self):
        self.font(9, color=MUTED)
        self.ctx.move_to(MARGIN, PAGE_HEIGHT - 29)
        self.ctx.show_text("Tucker Vana · Lavatune · October 2026")
        self.ctx.move_to(PAGE_WIDTH - MARGIN - 32, PAGE_HEIGHT - 29)
        self.ctx.show_text(f"{len(self.pages) + 1}")
        self.pages.append(self.surface)

    def font(self, size=11.5, bold=False, code=False, color=INK):
        self.ctx.select_font_face("DejaVu Sans Mono" if code else "DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        self.ctx.set_font_size(size * (0.86 if code else 1))
        self.ctx.set_source_rgb(*color)

    def ensure(self, height):
        if self.y + height > PAGE_HEIGHT - MARGIN:
            self.new_page()

    def wrapped(self, parts, size, width=TEXT_WIDTH):
        lines, line, used = [], [], 0
        for text, bold, code, target in parts:
            for token in re.findall(r"\s+|\S+", text):
                self.font(size, bold, code)
                length = self.ctx.text_extents(token).x_advance
                if used + length > width and line and token.strip():
                    while line and not line[-1][0].strip():
                        line.pop()
                    lines.append(line)
                    line, used = [], 0
                if not line and not token.strip():
                    continue
                line.append((token, bold, code, target, length))
                used += length
        if line:
            lines.append(line)
        return lines

    def paragraph(self, text, size=11.5, line_height=16, gap=9, color=INK, force_bold=False):
        parts = fragments(text)
        if force_bold:
            parts = [(text, True, False, None) for text, _, _, _ in parts]
        lines = self.wrapped(parts, size)
        self.ensure(len(lines) * line_height + gap)
        for line in lines:
            self.y += line_height
            x = MARGIN
            for token, bold, code, target, advance in line:
                self.font(size, bold, code, TEAL if target else color)
                self.ctx.move_to(x, self.y)
                if target and token.strip():
                    self.ctx.tag_begin(cairo.TAG_LINK, f"uri='{target}'")
                self.ctx.show_text(token)
                if target and token.strip():
                    self.ctx.tag_end(cairo.TAG_LINK)
                x += advance
        self.y += gap

    def heading(self, text):
        self.ensure(390 if text == "Results" else 82)
        self.y += 10
        self.paragraph(text, size=17, line_height=22, gap=9, force_bold=True)

    def figure(self):
        image = cairo.ImageSurface.create_from_png(str(ROOT / "publication/figure.png"))
        scale = TEXT_WIDTH / image.get_width()
        height = scale * image.get_height()
        self.ensure(height + 13)
        self.ctx.save()
        self.ctx.translate(MARGIN, self.y)
        self.ctx.scale(scale, scale)
        self.ctx.set_source_surface(image, 0, 0)
        self.ctx.paint()
        self.ctx.restore()
        self.y += height + 13

    def table(self, rows):
        widths = [79, 139, 134, TEXT_WIDTH - 352]
        size = 9.2
        prepared = [[self.wrapped(fragments(cell), size, width - 12) for cell, width in zip(row, widths)] for row in rows]
        heights = [max(len(lines) for lines in row) * 14 + 12 for row in prepared]
        self.ensure(sum(heights) + 12)
        for index, (row, height) in enumerate(zip(prepared, heights)):
            if index == 0:
                self.ctx.set_source_rgb(0.92, 0.95, 0.93)
                self.ctx.rectangle(MARGIN, self.y, TEXT_WIDTH, height)
                self.ctx.fill()
            x = MARGIN
            for lines, width in zip(row, widths):
                baseline = self.y + 17
                for line in lines:
                    self.font(size, bold=index == 0)
                    self.ctx.move_to(x + 6, baseline)
                    self.ctx.show_text("".join(item[0] for item in line))
                    baseline += 14
                x += width
            self.y += height
            self.ctx.set_source_rgb(0.82, 0.85, 0.83)
            self.ctx.set_line_width(0.5)
            self.ctx.move_to(MARGIN, self.y)
            self.ctx.line_to(PAGE_WIDTH - MARGIN, self.y)
            self.ctx.stroke()
        self.y += 12

    def save(self):
        self.finish_page()
        output = ROOT / "publication/article.pdf"
        with cairo.PDFSurface(str(output), PAGE_WIDTH, PAGE_HEIGHT) as pdf:
            pdf.set_metadata(cairo.PDF_METADATA_TITLE, "Rendering less in a Python visualizer")
            pdf.set_metadata(cairo.PDF_METADATA_AUTHOR, "Tucker Vana")
            ctx = cairo.Context(pdf)
            for index, page in enumerate(self.pages):
                ctx.set_source_surface(page, 0, 0)
                ctx.paint()
                ctx.show_page()
                preview = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(PAGE_WIDTH * 2), int(PAGE_HEIGHT * 2))
                view = cairo.Context(preview)
                view.scale(2, 2)
                view.set_source_surface(page, 0, 0)
                view.paint()
                preview.write_to_png(str(ROOT / "evidence" / f"article-page-{index + 1}.png"))
        print(f"Rendered {len(self.pages)} pages to {output}")


def main():
    lines = (ROOT / "publication/article.md").read_text().splitlines()
    document = Document()
    document.paragraph("ENGINEERING · LAVATUNE", size=9, line_height=13, gap=13, color=TEAL, force_bold=True)
    document.paragraph(lines[0].removeprefix("# "), size=29, line_height=35, gap=21, force_bold=True)
    index = 1
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("## "):
            document.heading(line[3:])
        elif line.startswith("!["):
            document.figure()
        elif line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [value.strip() for value in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                    rows.append(cells)
                index += 1
            document.table(rows)
            continue
        else:
            paragraph = [line]
            index += 1
            while index < len(lines) and lines[index].strip() and not lines[index].startswith(("#", "|", "![")):
                paragraph.append(lines[index].strip())
                index += 1
            document.paragraph(" ".join(paragraph))
            continue
        index += 1
    document.save()


if __name__ == "__main__":
    main()
