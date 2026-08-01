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
OrganismFieldRenderer -> shape and attention grids
        |
        v
     curses -> glyphs and terminal colors
```

The divisions are deliberate. Audio analysis does not know about brightness, physics does not know about terminal glyphs, and the terminal renderer does not decide how sound moves a body.

## Modules

`audio.py` launches one local capture backend and reads signed 16-bit PCM. `bands` analysis uses a small Goertzel filter bank. `atlas` analysis skips frequency detection and turns recent envelope history into eight approximate values for lower CPU use.

`organism.py` has three stages:

1. `AudioForceMapper` converts signal measurements into bass, voice, detail, transient, tempo, and spectral forces.
2. `AcousticOrganism` applies those forces to persistent bodies in normalized coordinates.
3. `OrganismFieldRenderer` rasterizes body shape and local attention into separate values from `0.0` to `1.0`.

`app.py` owns the curses event loop, controls, tile layout, and final glyph/color transfer. `LavaField` is the narrow adapter between the UI and the three organism stages.

`media.py` polls `playerctl` on a separate thread. Metadata is optional and never participates in audio analysis.

`config.py` contains only settings that the current runtime consumes. Profiles change groups of settings; scenes change presentation; product presets combine both for common use.

## Coordinates and resizing

Bodies keep positions, velocity, and character in normalized `0.0` to `1.0` coordinates. A resize changes `TileComposition` and the size of the scalar field, but does not recreate the bodies. Weak habitat anchors gradually recompose the same identities into a centered micro body, vertical chimney, open basin, or horizontal current. This is why a narrow tile and a wide tile feel related instead of restarting as unrelated animations.

Compact mode adjusts simulated cell width against a target cell budget. The curses layer then interpolates the scalar field back across available terminal columns. That keeps tiny tiles legible and larger tiles affordable.

## Brightness budget

The force mapper never emits color or luminance. Most field intensity comes from persistent body mass. Detail adds surface texture. A transient is assigned to one pitch-adjacent body, where it creates a decaying attention layer near the struck edge. The terminal renderer reserves the final palette color for that layer; ordinary body intensity cannot spend it. Tests measure visible, bright, and saturated area so a loud source cannot wash the whole tile out.

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
- Shape and attention brightness: `OrganismFieldRenderer` in `organism.py`
- Glyphs, palettes, controls, and tile layout: `app.py`
- Power defaults and presets: `config.py` and the preset tables in `app.py`

Behavior changes should be covered by the synthetic audio and field-metric tests before being judged interactively in a real terminal.
