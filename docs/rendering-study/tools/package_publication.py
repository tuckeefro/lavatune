"""Export an allowlisted publication packet; exclude unrelated or private work."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_FILES = [
    "README.md", "LICENSE",
    "publication/article.md", "publication/article.html", "publication/methods.md",
    "publication/linkedin-post.txt", "publication/talk-outline.md",
    "tools/benchmark_study.py", "tools/workload_probe.py", "tools/check_terminal.py",
    "tools/verify_public_sources.py", "tools/draw_figure.py", "tools/render_document.py", "tools/render_pdf.py",
    "tools/package_publication.py", "tests/test_evidence.py",
    "evidence/public-source-manifest.json", "evidence/public-verification.json",
    "evidence/terminal-verification.json", "evidence/terminal-tests.log",
    "evidence/lavatune-public-tests.log", "evidence/lavatune-public-cli.log",
    "evidence/evidence-tests.log", "evidence/main-study/benchmark-runs.csv",
    "evidence/publication-validation.json",
    "evidence/main-study/benchmark-summary.json", "evidence/main-study/workload.json",
    "evidence/first-harness-attempt-terminal-tests.log",
    "evidence/first-harness-attempt-terminal-verification.json",
    "evidence/first-harness-attempt-note.json",
    "evidence/pilot-120/benchmark-runs.csv", "evidence/pilot-120/benchmark-summary.json",
]
BINARY_FILES = ["publication/figure.png", "publication/figure.svg", "publication/figure.pdf", "publication/article.pdf", "evidence/main-study/benchmark.sqlite"]


def public_bytes(relative):
    data = (ROOT / relative).read_bytes()
    if relative.endswith(".log") or "verification.json" in relative:
        text = data.decode().replace(str(ROOT / "_sources/lavatune-public"), "<source>")
        return text.encode()
    return data


def main():
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    manifest = json.loads((ROOT / "evidence/public-source-manifest.json").read_text())
    destination = output / "lavatune-rendering-study.zip"
    entries = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in TEXT_FILES + BINARY_FILES:
            archive.writestr("lavatune-rendering-study/" + relative, public_bytes(relative))
            entries.append(relative)
        for record in manifest["files"]:
            relative = "_sources/lavatune-public/" + record["path"]
            archive.write(ROOT / relative, "lavatune-rendering-study/" + relative)
            entries.append(relative)
    (output / "packet-manifest.json").write_text(json.dumps({"archive": destination.name, "files": entries}, indent=2) + "\n")
    print(json.dumps({"archive": str(destination), "files": len(entries), "bytes": destination.stat().st_size}))


if __name__ == "__main__":
    main()
