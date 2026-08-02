# Architecture

Lavatune has one data path:

```text
Linux monitor process
        |
        v
    AudioCapture  ->  AudioFrame
        |
        v
 AudioForceMapper ->  AudioForces
        |
        v
 AcousticOrganism -> persistent Body objects
        |
        v
OrganismFieldRenderer -> mass, surface, and attention grids
        |
        v
 Text/Fluid material -> curses glyphs and terminal colors
```

The divisions are deliberate. Audio analysis does not know about brightness, physics does not know about terminal glyphs, and the terminal renderer does not decide how sound moves a body.

## Modules

`audio.py` launches one local capture backend and reads signed 16-bit PCM. `bands` analysis uses a small Goertzel filter bank. `atlas` analysis skips frequency detection and turns recent envelope history into eight approximate values for lower CPU use.

`organism.py` has three stages:

1. `AudioForceMapper` converts signal measurements into bass, voice, detail, transient, tempo, and spectral forces.
2. `AcousticOrganism` applies those forces to persistent bodies in normalized coordinates.
3. `OrganismFieldRenderer` rasterizes body mass, surface activity, and local attention into separate values from `0.0` to `1.0`.

`materials.py` maps those semantic channels into Text or foreground-only Fluid cells. It contains no curses state, audio analysis, or body physics, so output behavior can be snapshot-tested directly. `app.py` owns the curses event loop, controls, tile layout, palette capacity, and final terminal writes. `LavaField` is the narrow adapter between the UI and the organism stages.

`media.py` polls `playerctl` on a separate thread. Metadata is optional and never participates in audio analysis.

`doctor.py` checks platform and terminal capabilities, discovers local helper programs, and can open the normal capture path briefly to distinguish missing dependencies from an inaccessible or incorrect monitor source.

`config.py` contains only settings that the current runtime consumes. Profiles change groups of settings; legacy scenes remain config-compatible; product presets change operating behavior without replacing presentation. Default launches layer versioned XDG preferences over built-ins. An explicit TOML config is self-contained, ignores those preferences, and disables preference writes. Preference updates use a same-directory temporary file and atomic replacement.

## Coordinates and resizing

Bodies keep positions, velocity, and character in normalized `0.0` to `1.0` coordinates. Radius and collision calculations convert those coordinates through an approximate terminal cell aspect ratio, so a body keeps the same physical silhouette in a narrow chimney and a wide current. A resize changes `TileComposition` and the size of the scalar field, but does not recreate the bodies.

Weak habitat anchors establish home regions while a continuous circulation field does most of the movement. Rising transients can emit up to three short-lived pressure waves from pitch-dependent tile edges. A wave travels through the shared vessel, disturbs each body when it arrives, and decays independently of the local afterglow assigned to the pitch-adjacent body. This is why the reaction can be believable without making every body jump on the same frame.

The first viewport seeds the cast in its actual habitat and translates its mass-weighted center near the visual midpoint. Later resizes never reseed it. A weak group correction continually nudges the centroid rather than pulling bodies individually, preserving internal circulation and momentum.

Compact mode adjusts simulated cell width against a target cell budget. The curses layer then interpolates the scalar field back across available terminal columns. That keeps tiny tiles legible and larger tiles affordable.

## Brightness budget

The force mapper never emits color or luminance. Most field intensity comes from a soft union of persistent body mass, which lets skirts meet without summing into a saturated slab. Surface activity and attention remain separate through rasterization. A material combines them using bounded Weight, Edge, and Afterglow gains. The terminal renderer reserves the final palette color for attention; ordinary body intensity cannot spend it. Tests measure visible, bright, and saturated area so a loud source cannot wash the whole tile out.

Fluid estimates the local mass-field gradient once per terminal cell and uses it to classify four foreground-only quadrants. Adjacent cells therefore describe one continuous contour instead of a decorative pixel pattern, while dense body cores remain solid. It does not allocate foreground/background color combinations, so transparent terminal backgrounds remain intact and palette-pair use stays bounded. Non-UTF-8 terminals fall back to Text.

## Threads and processes

The curses loop stays on the main thread. Audio capture and MPRIS polling each use one daemon thread:

- the audio thread blocks on PCM reads and keeps the latest few analyzed frames
- the media thread polls at a low fixed rate
- a small stderr-draining thread prevents an audio backend from blocking on its diagnostic pipe

Shutdown terminates and reaps the audio subprocess, stops both workers, and disables terminal focus reporting.

## Where to tune behavior

- Frequency and level response: `AudioCapture` in `audio.py`
- Mapping from sound to physical meaning: `AudioForceMapper` in `organism.py`
- Body motion, collisions, and wall response: `AcousticOrganism` in `organism.py`
- Semantic field rasterization: `OrganismFieldRenderer` in `organism.py`
- Material sampling and glyph choice: `materials.py`
- Palettes, controls, persistence, and tile layout: `app.py` and `config.py`
- Power defaults and presets: `config.py` and the preset tables in `app.py`

Behavior changes should be covered by the synthetic audio and field-metric tests before being judged interactively in a real terminal.
