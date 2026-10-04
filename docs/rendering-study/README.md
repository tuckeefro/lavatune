# Lavatune: a publication with inspectable evidence

**Start with the [article](publication/article.md).** The [offline web document](publication/article.html) and [PDF](publication/article.pdf) carry the same main argument. The [LinkedIn post](publication/linkedin-post.txt) introduces it; [figure.png](publication/figure.png) is ready to attach. A [talk outline](publication/talk-outline.md) builds from the article.

[Download the reproducible packet](https://github.com/tuckeefro/lavatune/raw/refs/heads/docs/rendering-evidence-2026-10/docs/rendering-study/dist/lavatune-rendering-study.zip)

At a 120 × 30 viewport, the recorded medians were 40.16 ms and 7.45 ms per simulated frame for Lavatune's scalar-field and contour strategies. This is a comparison of different visual representations on one machine. It excludes live capture and terminal output.

## Inspect the evidence

- [Methods and limitations](publication/methods.md)
- [All 30 observations](evidence/main-study/benchmark-runs.csv)
- [Summary and environment](evidence/main-study/benchmark-summary.json)
- [Diagnostic workload replay](evidence/main-study/workload.json)
- [Pinned public source manifest](evidence/public-source-manifest.json)
- [Terminal/core receipt](evidence/terminal-verification.json) and [test log](evidence/terminal-tests.log)
- [Full-suite receipt](evidence/public-verification.json) and [failure log](evidence/lavatune-public-tests.log)
- [Evidence-check log](evidence/evidence-tests.log)

The full upstream suite reported ten missing-Tkinter errors. The separate terminal/core subset passed 222 tests and excluded all 14 window tests. Eleven additional evidence checks passed. Earlier harness failures and the 120-frame pilot are retained and explained in the methods.

## Reproduce

Use Python 3.11 or later. The documented terminal checks were run on Linux. Measurement and validation use the standard library; optional figure generation uses Pycairo.

The downloadable archive includes `_sources/lavatune-public` at the exact workload commit. If obtaining only this directory from GitHub, fetch the workload first:

```bash
git clone https://github.com/tuckeefro/lavatune.git _sources/lavatune-public
git -C _sources/lavatune-public checkout --detach f79516e82b9b6383ea1d169be2937c9ba6a5a93d
python3 tools/verify_public_sources.py
python3 -m unittest discover -s tests -v
python3 tools/check_terminal.py --output evidence/my-terminal-check
python3 tools/benchmark_study.py --output evidence/my-reproduction
python3 tools/workload_probe.py --output evidence/my-reproduction/workload.json
```

New runs go into new output directories. Exact timings will vary. Source identity, complete observations, and internally consistent aggregation are the reproduction criteria; the published ratio is not a pass threshold.

## Publication status and provenance

This packet prepares a LinkedIn publication and a standalone document. It has not been posted to LinkedIn or accepted at a conference. The GitHub documentation branch provides a public evidence link when available. Lavatune and this analysis were developed with Codex under Tucker Vana's direction; see the pinned repository's authorship record. The application source and publication tools are provided under the included MIT license.
