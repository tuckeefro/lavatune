# Architecture

Lavatune has one data path:

```text
Linux monitor process
        |
        v
    AudioCapture  ->  bounded sequenced AudioFrames
        |                     |
        |              nonblocking notifier
        |
        v
 AudioForceMapper ->  AudioForces
        |                    |
        v                    v
  ReactionLatch       AffectiveTracker
        |                    |
        +---------+----------+
                  |
                  v
        AcousticOrganism -> persistent Body objects
        |
        v
        +-----------------------------+
        |                             |
        v                             v
 Fluid contour material       OrganismFieldRenderer
                                      |
                                      v
                              mass, surface, and
                               attention grids
                                      |
                                      v
                               Text material
        |                             |
        +--------------+--------------+
                       |
                       v
         sparse changed curses runs only
```

The divisions are deliberate. Audio analysis does not know about brightness, physics does not know about terminal glyphs, and the terminal renderer does not decide how sound moves a body.

## Modules

`audio.py` launches one local capture backend and reads signed 16-bit PCM. Normal listening uses a small Goertzel filter bank because its measured cost at the 1024-sample window is nearly identical to coarse analysis. `atlas` uses two one-pole filters in the envelope pass to retain broad low, mid, and high contrast at the larger low-power window.

`organism.py` has four stages:

1. `AudioForceMapper` converts signal measurements into bass, voice, detail, transient, tempo, spectral forces, and per-band deviation from recent context.
2. `AffectiveTracker` integrates those forces into weight, agitation, cohesion, tension, openness, release, intimacy, volatility, novelty, fragility, yearning, and catharsis. These are transparent acoustic posture axes, not classified emotions or genres.
3. `AcousticOrganism` applies immediate forces and slower posture to persistent bodies in normalized coordinates.
4. `OrganismFieldRenderer` rasterizes body mass, surface activity, and local attention into separate values from `0.0` to `1.0` for Text.

`materials.py` maps organism state into Text or foreground-only Fluid cells. Text prepares the semantic field once per source row and interpolates it across the viewport. Fluid takes the faster path: it prepares body geometry once, emits only occupied row spans, and caches the latest quantized contour instead of rasterizing a full scalar field. Neither material contains curses state, audio analysis, or body physics, so output behavior can be tested directly. `app.py` owns the curses event loop, reaction latch, multi-rate scheduler, controls, tile layout, palette capacity, and final terminal writes. `LavaField` is the narrow adapter between the UI and the organism stages.

`media.py` polls `playerctl` on a separate thread. Metadata is optional and never participates in audio analysis.

`doctor.py` checks platform and terminal capabilities, discovers local helper programs, and can open the normal capture path briefly to distinguish missing dependencies from an inaccessible or incorrect monitor source.

`config.py` contains only settings that the current runtime consumes. Profiles change groups of settings; legacy scenes remain config-compatible; product presets change operating behavior without replacing presentation. Default launches layer versioned XDG preferences over built-ins. An explicit TOML config is self-contained, ignores those preferences, and disables preference writes. Preference updates use a same-directory temporary file and atomic replacement.

## Coordinates and resizing

Bodies keep positions, velocity, and character in normalized `0.0` to `1.0` coordinates. Radius and collision calculations convert those coordinates through an approximate terminal cell aspect ratio, so a body keeps the same physical silhouette in a narrow chimney and a wide current. A resize changes `TileComposition` and the size of the scalar field, but does not recreate the bodies.

Weak habitat anchors establish home regions while a continuous circulation field does most of the movement. Rising transients can emit up to three short-lived pressure waves from pitch-dependent tile edges. A wave travels through the shared vessel, disturbs each body when it arrives, and decays independently of the local afterglow assigned to the pitch-adjacent body. Each frequency band keeps a noise-aware 2.4-second rolling baseline after a short warmup. Only meaningful upward deviation from that baseline feeds a body's faster spike envelope; raw loudness and ordinary attacks cannot sharpen it. The point and impulse collapse before afterglow or phrase posture fades. This is why the reaction can be believable without making every body jump on the same frame.

The first viewport seeds the cast in its actual habitat and translates its mass-weighted center near the visual midpoint. Later resizes never reseed it. A weak group correction continually nudges the centroid rather than pulling bodies individually, preserving internal circulation and momentum.

For Text, compact mode adjusts simulated cell width against a target cell budget and the material interpolates the scalar field back across available terminal columns. Fluid instead composes bodies in the actual viewport and computes row spans at two vertical samples per terminal row. Both paths preserve normalized body state through resize.

## Brightness budget

The force mapper never emits color or luminance. Most field intensity comes from a soft union of persistent body mass, which lets skirts meet without summing into a saturated slab. Surface activity and attention remain separate through rasterization. A material combines them using bounded Weight, Edge, and Afterglow gains. The terminal renderer reserves the final palette color for attention; ordinary body intensity cannot spend it. Tests measure visible, bright, and saturated area so a loud source cannot wash the whole tile out.

Fluid intersects analytic body ellipses with the top and bottom halves of each terminal row, merges overlapping intervals, and selects foreground-only quadrant glyphs at their boundaries. Adjacent cells therefore describe continuous contours, while body cores remain solid. Local attention is evaluated only near the impacted body edge, separately from ordinary body color. Fluid does not allocate foreground/background color combinations, so transparent terminal backgrounds remain intact and palette-pair use stays bounded. Non-UTF-8 terminals fall back to Text.

## Cadence and terminal writes

Audio capture publishes a bounded sequence of analyzed frames and signals a nonblocking pipe. The main loop waits on that pipe and keyboard input instead of polling every 10 milliseconds, then maps every retained frame in order. `ReactionLatch` holds short attacks until the next visual frame, so prompt response does not require prompt terminal redraws.

Rendering cadence follows a hysteretic acoustic state rather than one fixed display rate. Resting, breathing, engaged, and burst states draw at 2, 4, 8, and 14 FPS. Physics advances independently at 2, 4, 6, and 8 FPS, using bounded elapsed-time substeps. Release starts one short burst when it crosses the meaningful threshold; its slower posture can remain visible without continuously extending that expensive state. The `power-save` profile caps display cadence at 6 FPS.

The curses layer caches only occupied visual cells and writes sparse runs whose glyph or color changed, including blanks needed to clear an old contour. A resize, material change, palette change, or diagnostic overlay invalidates that cache. This keeps the daily view cheap while preserving immediate feedback for interaction and sudden sound.

## Threads and processes

The curses loop stays on the main thread. Audio capture and MPRIS polling each use one daemon thread:

- the audio thread blocks on PCM reads, keeps at most eight sequenced analyzed frames, and signals the main loop
- the media thread polls at a low fixed rate
- a small stderr-draining thread prevents an audio backend from blocking on its diagnostic pipe

Shutdown terminates and reaps the audio subprocess, stops both workers, and disables terminal focus reporting.

## Where to tune behavior

- Frequency and level response: `AudioCapture` in `audio.py`
- Mapping from sound to physical meaning: `AudioForceMapper` in `organism.py`
- Body motion, collisions, and wall response: `AcousticOrganism` in `organism.py`
- Semantic field rasterization for Text: `OrganismFieldRenderer` in `organism.py`
- Text row preparation and Fluid contour rendering: `materials.py`
- Palettes, controls, persistence, and tile layout: `app.py` and `config.py`
- Power defaults and presets: `config.py` and the preset tables in `app.py`

Behavior changes should be covered by the synthetic audio and field-metric tests before being judged interactively in a real terminal.
