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
