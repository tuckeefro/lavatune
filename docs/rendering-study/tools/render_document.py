"""Render the controlled Markdown article to a self-contained, script-free HTML file."""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = "https://github.com/tuckeefro/lavatune/blob/docs/rendering-evidence-2026-10/docs/rendering-study/publication/"
CSS = """+:root { color-scheme: light; --ink:#1a2630; --muted:#56636e; --accent:#00645e; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:#faf9f6; font:20px/1.65 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
main { max-width:980px; margin:0 auto; padding:54px 40px 72px; }
header, section { max-width:780px; margin:0 auto; }
.kicker { font-size:13px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); margin-bottom:16px; }
h1 { font-size:clamp(34px,5vw,54px); line-height:1.1; letter-spacing:-.025em; margin:0 0 25px; max-width:820px; }
h2 { font-size:29px; line-height:1.25; margin:44px 0 18px; letter-spacing:-.015em; }
h3 { font-size:23px; line-height:1.3; margin:30px 0 12px; }
p { margin:0 0 22px; }
strong { font-weight:700; }
a { color:var(--accent); text-underline-offset:.18em; text-decoration-thickness:1px; overflow-wrap:anywhere; }
a:hover { text-decoration-thickness:2px; }
a:focus-visible { outline:3px solid var(--accent); outline-offset:4px; }
code { font-size:.84em; padding:.13em .25em; background:#edf0ed; border-radius:3px; overflow-wrap:anywhere; }
pre { padding:18px; overflow:auto; background:#edf0ed; border-radius:5px; line-height:1.45; }
pre code { padding:0; white-space:pre; }
figure { margin:30px -45px; }
figure img { display:block; width:100%; height:auto; }
figcaption { color:var(--muted); font-size:14px; margin:10px 45px 0; line-height:1.5; }
.table-scroll { overflow-x:auto; margin:26px 0; }
table { width:100%; border-collapse:collapse; font-size:16px; line-height:1.5; font-variant-numeric:tabular-nums; }
th { text-align:left; background:#eaf0ec; vertical-align:bottom; }
td,th { padding:12px 10px; border-bottom:1px solid #d8dfda; }
td:not(:first-child),th:not(:first-child) { text-align:right; }
ul,ol { padding-left:24px; margin:0 0 24px; }
li { margin-bottom:10px; }
.toolbar { display:flex; gap:20px; flex-wrap:wrap; border-bottom:1px solid #d8dfda; padding-bottom:18px; margin:25px 0 34px; font-size:15px; }
.footer { border-top:1px solid #d8dfda; padding-top:22px; margin-top:42px; color:var(--muted); font-size:14px; }
@media(max-width:620px) { body {font-size:18px;} main {padding:30px 22px 44px;} h2 {font-size:26px;} figure {margin:24px -18px;} figcaption {margin:10px 18px 0;} table {font-size:14px;} td,th {padding:9px 7px;} }
@page { size:A4; margin:18mm; }
@media print {
 body {background:white; font-size:11pt; line-height:1.45;} main {max-width:none; padding:0;} header,section {max-width:none;}
 h1 {font-size:30pt; margin-bottom:16pt;} h2 {font-size:17pt; margin:23pt 0 10pt; break-after:avoid;} h3 {font-size:13pt; break-after:avoid;}
 p {margin-bottom:12pt;} .toolbar {display:none;} figure {margin:16pt 0; break-inside:avoid;} figcaption {margin:6pt 0 0; font-size:8pt;}
 table {font-size:9pt; break-inside:avoid;} td,th {padding:7pt;} .table-scroll {overflow:visible; margin:16pt 0;}
 a {color:#164d49;} .kicker {font-size:8pt; margin-bottom:12pt;} .footer {font-size:8pt;}
}
"""


def inline(value: str) -> str:
    value = html.escape(value, quote=True)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    def link(match):
        text, target = match.groups()
        if target.endswith(".md") and ":" not in target:
            target = WEB + target
        return f'<a href="{target}">{text}</a>'
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, value)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)


def body(markdown: str) -> str:
    lines = markdown.splitlines()
    rendered = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("# "):
            index += 1
            continue
        if line.startswith("## "):
            rendered.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("### "):
            rendered.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("!["):
            match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line)
            alt, name = match.groups()
            image_path = ROOT / "publication" / name
            payload = base64.b64encode(image_path.read_bytes()).decode()
            rendered.append(f'<figure><img width="1600" height="1000" alt="{html.escape(alt, quote=True)}" src="data:image/png;base64,{payload}"><figcaption>Median of five run averages; whiskers show their minimum and maximum. Different visual representations; live capture and terminal output excluded.</figcaption></figure>')
        elif line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                    rows.append(cells)
                index += 1
            head = "".join(f'<th scope="col">{inline(cell)}</th>' for cell in rows[0])
            values = "".join("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>" for row in rows[1:])
            rendered.append(f'<div class="table-scroll"><table><caption style="text-align:left;margin-bottom:8px">Recorded median compute times</caption><thead><tr>{head}</tr></thead><tbody>{values}</tbody></table></div>')
            continue
        else:
            paragraph = [line]
            index += 1
            while index < len(lines) and lines[index].strip() and not lines[index].startswith(("#", "|", "![")):
                paragraph.append(lines[index].strip())
                index += 1
            rendered.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            continue
        index += 1
    return "\n".join(rendered)


def main():
    markdown = (ROOT / "publication/article.md").read_text()
    title = markdown.splitlines()[0].removeprefix("# ")
    content = body(markdown)
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="author" content="Tucker Vana"><meta name="description" content="A reproducible comparison of two Python audio-visualizer rendering strategies, with measurements and explicit limits.">
<title>{html.escape(title)} — Tucker Vana</title><style>{CSS}</style></head>
<body><main><header><div class="kicker">Engineering · Lavatune</div><h1>{html.escape(title)}</h1>
<nav class="toolbar" aria-label="Supporting evidence"><a href="{WEB}methods.md">Methods and reproduction</a><a href="https://github.com/tuckeefro/lavatune/tree/docs/rendering-evidence-2026-10/docs/rendering-study">Evidence packet</a></nav></header>
<section aria-label="Case study">{content}</section><section class="footer" aria-label="Document information">October 4, 2026 · Self-contained document: no external scripts, fonts, or image requests. Prepared for publication; conference acceptance has not occurred.</section></main></body></html>'''
    (ROOT / "publication/article.html").write_text(document)
    print("Rendered publication/article.html")


if __name__ == "__main__":
    main()
