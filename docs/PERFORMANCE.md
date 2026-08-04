# Performance

Lavatune includes a deterministic benchmark for the audio-force, body-motion, scalar-field, and attention-field pipeline:

```bash
python scripts/benchmark.py
python scripts/benchmark.py --json
```

The benchmark cycles through synthetic silence, speech, bass, music, and transient frames. It does not include live PCM capture, terminal writes, frame pacing, or compositor overhead. The reported pipeline rate is capacity, not the application's configured display FPS.

## Development baseline

Measured on the original Linux development machine with Python 3.13.5 on x86-64, using 500 measured frames per shape:

| Habitat | Simulated cells | Milliseconds/frame | Pipeline frames/second |
| --- | ---: | ---: | ---: |
| Micro | 144 | 0.443 | 2257.8 |
| Chimney | 640 | 3.846 | 260.0 |
| Basin | 792 | 5.884 | 169.9 |
| Current | 1080 | 7.872 | 127.0 |

Peak resident memory for that benchmark process was approximately 18.8 MiB. Results vary with Python build, CPU, terminal size, and enabled profile, so these values are a comparison baseline rather than a compatibility guarantee.

CI runs a short smoke benchmark to catch broken execution. It does not enforce timing thresholds across shared GitHub runners.

## Material and terminal path

The end-to-end material benchmark compares the alpha Fluid path with the current contour renderer:

```bash
python scripts/benchmark_render.py
python scripts/benchmark_render.py --json
```

Measured on the same machine at 120 by 30 terminal cells over 120 synthetic frames:

| Render path | Milliseconds/frame |
| --- | ---: |
| Alpha scalar field + Fluid | 43.089 |
| Analytic contour Fluid with surface-wave memory | 7.6–10.5 |
| Unchanged cached contour | 0.011 |
| Prepared-row Text | 21.550 |

Recent 120-frame runs place the contour Fluid path between 5.68 and 7.29 times faster per rendered frame than the alpha path on this development host. It prepares body geometry once and emits occupied row spans rather than a full matrix. The surface refinement adds four persistent scalars per body and evaluates a localized wave only at already-occupied contour edges; it adds no full-screen pass, new simulation grid, or higher display cadence. Less than one percent of this deliberately changing synthetic sequence reused the one-entry quantized contour cache; calmer real sequences can reuse more. The cached figure isolates a repeated material call and does not include body simulation.

### Experimental Volume refinement checkpoint

The concentrated thermal-wax refinement was measured separately on 2026-08-03 with the same Python 3.13.5 x86-64 host, 120 by 30 terminal cells, 120 synthetic frames, and the command above. A single measurement immediately before the refinement captured the current Volume baseline; four isolated measurements after it provide a range so one scheduler fluctuation is not presented as precision:

| Volume checkpoint | Milliseconds/frame |
| --- | ---: |
| Current pre-refinement baseline | 29.879 |
| Refined Volume, median of four runs | 32.396 |
| Refined Volume range | 31.098–33.199 |
| Median change from baseline | +2.517 (+8.4%) |

The paired refined runs placed Volume between 3.64 and 5.09 times the analytic contour Fluid cost. Most of that cost remains the existing sparse four-quadrant, depth-tested projection of four bodies. The refinement adds six fixed pair-distance and bridge scores, per-body thermal/history scalars, and one four-body visual-leader selection; it does not add a field pass, increase subcell samples, expand projected bounds, or raise render/physics cadence. Those bounded additions explain the observed increase, with normal host scheduling noise visible in the range. Volume therefore remains experimental and configuration-only; this checkpoint does not justify changing the default Fluid renderer or the fixed CPU envelope.

Lavatune draws at an activity-dependent 2/4/8/14 FPS and advances physics independently at 2/4/6/8 FPS. The `power-save` profile caps active display cadence at 6 FPS. Audio arrival and keyboard input wake the main loop through `select`, replacing the former 100 Hz polling wakeup. Every retained audio frame is mapped, but attacks are latched until a draw and slower affective state uses constant-work rolling values rather than stored history or inference.

This benchmark includes body simulation and material generation but not live PCM capture, curses calls, the terminal emulator, or the desktop compositor. It therefore demonstrates reduced work inside Lavatune, not a promised number of laptop watts. Real power should be checked at steady state with the same terminal size, audio source, and browser workload.

## Analysis cost

At the normal 16 kHz, 1024-sample listening window, coarse Atlas analysis measured 0.405 ms/frame and eight-band Goertzel analysis measured 0.425 ms/frame. The roughly 0.020 ms difference is too small to justify discarding tonal information, so normal listening uses real bands. At the low-power 12 kHz, 3072-sample window, Atlas measured 0.875 ms/frame versus 1.527 ms/frame for Goertzel and remains the appropriate choice. These figures measure analysis only and vary by machine.
