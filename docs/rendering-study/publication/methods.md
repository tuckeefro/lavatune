# Measurement methods and reproduction

## Question and unit

How does compute time differ between Lavatune's existing scalar-field/Fluid path and analytic-contour/Fluid path as the terminal viewport grows?

One observation is one run's elapsed wall-clock milliseconds divided by 200 simulated frames. There are five observations per path and viewport. Reported central values are the medians of those five run averages. The figure's whiskers show their minimum and maximum; they are not confidence intervals or frame-level percentiles.

## Fixed source and protocol

Repository: `tuckeefro/lavatune`. Workload commit: `f79516e82b9b6383ea1d169be2937c9ba6a5a93d`.

The [manifest](../evidence/public-source-manifest.json) contains the 72 public source files' Git blob IDs and SHA-256 hashes. Verification reads those files without editing them. The study refuses mismatched sources and an output directory that already contains measurements.

| Item | Setting |
|---|---|
| Viewports, in execution order | 60 × 18; 90 × 24; 120 × 30 |
| Body configuration | `LavaConfig(blobs=4)` |
| Input | Existing `synthetic_frame`, indices 0–199; two complete 100-frame cycles |
| Simulation | Existing harness resets `_last_step_at` before each step; `atlas` profile supplies the nominal time step |
| Scalar path | Field width `max(10, width // 3)`; rasterization enabled; `Fluid.cell` called for every output cell |
| Contour path | Field at full viewport dimensions; rasterization disabled; surface ripples enabled; `Fluid.render_spans` |
| Repeats | Five per method and size; 30 observations; 6,000 timed feature frames in total |
| Path order | Scalar first on repeats 0, 2, 4; contour first on repeats 1, 3 |
| Warmup | Twenty unrecorded frames per path/size on separate field instances; recorded simulations start fresh |
| Hardware / runtime | Intel i5-4570 at nominal 3.20 GHz; Linux x86_64; Python 3.13.5 |
| Time boundary | Existing harness's `perf_counter` around feature construction, mapping, simulation, and material computation |

The scalar and contour paths have different field sizes, shape behavior, and force inputs (`field_frame` versus `field.forces`). This is a strategy comparison, not a pixel-equivalent algorithm benchmark or a single-factor ablation. The existing contour material is a singleton; the upstream harness resets cache counters, not all material state. The diagnostic replay is separate from the timed runs.

Live PCM capture, curses writes, terminal-emulator rendering, the compositor, and power consumption are excluded. CPU frequency and competing desktop work were not controlled. There is one machine and one synthetic sequence; no population-level inference or general complexity claim is warranted.

## Results and variation

| Viewport | Scalar median [min–max], ms/frame | Contour median [min–max], ms/frame | Ratio of medians |
|---|---:|---:|---:|
| 60 × 18 | 11.38 [11.32–11.64] | 3.62 [3.57–3.74] | 3.14× |
| 90 × 24 | 23.23 [22.53–24.09] | 5.09 [4.88–5.23] | 4.57× |
| 120 × 30 | 40.16 [39.97–43.23] | 7.45 [7.33–7.60] | 5.39× |

See [raw observations](../evidence/main-study/benchmark-runs.csv), [summary and environment](../evidence/main-study/benchmark-summary.json), and the SQLite database in the downloadable packet. SQLite holds constrained observation rows and a **mean** view; the article's **medians** are calculated separately in Python. The CSV hash is recorded in the summary.

An earlier 120-frame pilot is retained under `evidence/pilot-120/`. It produced ratios of 3.37×, 4.69×, and 5.61×. The publication uses the later complete-cycle protocol, including its less favorable largest-viewport ratio. The pilot overweights the initial silence segment; it is not pooled with the main run.

## Diagnostic replay

[workload.json](../evidence/main-study/workload.json) comes from a separate 200-frame replay following the same path settings. At the largest viewport the scalar path evaluated 720,000 output cells, 130,462 of which were nonblank. The contour path emitted 128,392 occupied cells across the replay and recorded 0 cache hits / 200 misses.

Emission count omits the contour renderer's internal candidate-cell, intersection, and shading work. The outputs differ. Neither count is a direct estimate of instructions executed or seconds saved.

## Verification and failures

- Full upstream suite: 236 tests, ten errors for unavailable Tkinter. This result remains a failure; see the retained full-suite log.
- Separate terminal/core subset: 222 tests passed; all 14 `test_window` methods were explicitly excluded. This includes Linux PTY integration checks using demo inputs, not real audio capture.
- Evidence checks: eleven tests passed for paired observations, duplicate and invalid rows, SQLite constraints and roundtrip, recomputed summaries, and the CSV hash.
- An initial subset runner omitted `PYTHONPATH` for its child processes. Two PTY tests failed. The runner was corrected and rerun; the first receipt and explanation are retained. No upstream application source was changed.

These checks establish specific contracts, not overall product quality, GUI correctness, or end-to-end performance. The historical successful [upstream CI run](https://github.com/tuckeefro/lavatune/actions/runs/36896035899) is separate evidence from this local environment.

## Execute from the packet root

Python 3.11 or later and Linux are required for the documented terminal checks. The workload and measurement scripts use the Python standard library. Tkinter is required for the full window suite; on Debian it is provided by `python3-tk`.

```bash
python3 tools/verify_public_sources.py
python3 -m unittest discover -s tests -v
python3 tools/check_terminal.py --output evidence/my-terminal-check
python3 tools/benchmark_study.py --output evidence/my-reproduction
python3 tools/workload_probe.py --output evidence/my-reproduction/workload.json
```

The archive includes the verified public workload in `_sources/lavatune-public`, with its MIT license. If working from the GitHub documentation directory rather than the archive, obtain that workload first:

```bash
git clone https://github.com/tuckeefro/lavatune.git _sources/lavatune-public
git -C _sources/lavatune-public checkout --detach f79516e82b9b6383ea1d169be2937c9ba6a5a93d
```

Exact timings will differ. A reproduction succeeds when source verification passes, the design contains all 30 unique observations, inputs and measurement boundaries match, and aggregation agrees with the raw data. Matching the published speed ratio is not an acceptance criterion.

## Next experiment that could change the decision

Instrument publish, consumption, and draw-submission timestamps for identified synthetic feature events through the real curses loop. Run quiet and burst cadence at all three viewport sizes, including an intentional consumer stall. Produce a per-event CSV and latency/gap figure with an explicit definition of which draw used each event. Accept the result only if sequence conservation accounts for every published, retained, consumed, and discarded event and timestamps use one monotonic clock. Stop making a renderer-focused latency claim if scheduling or output dominates, or if events cannot be matched unambiguously to draws. Draw submission still does not measure photons on screen.
