# Lavatune

[![CI](https://github.com/tuckeefro/lavatune/actions/workflows/ci.yml/badge.svg)](https://github.com/tuckeefro/lavatune/actions/workflows/ci.yml)

> **Naming note:** Lavatune is the project's working codename. The Python package and command keep that name during the alpha period so the implementation can stabilize before the public product name is chosen.

Lavatune is a local-first, terminal-native acoustic organism for Linux. It occupies a small terminal tile, keeps recognizable floating bodies alive during silence, and turns system audio into buoyant motion, deformation, wall pressure, and brief afterglow.

It is designed as a quiet desktop companion rather than a bar equalizer: sound changes the organism's behavior without mapping every sample to a block or flash.

## Status

Alpha. The core experience and packaging are usable, but visual defaults and the public name may change before `1.0`.

The current implementation targets Linux. A lightweight native macOS sibling is planned around public Core Audio process taps, local opt-in metadata adapters, and shared acoustic behavior fixtures. It will not use screen capture, private media frameworks, or network account APIs. See [`docs/MACOS.md`](docs/MACOS.md).

## Features

- reacts to system output through PipeWire, PulseAudio, or FFmpeg
- diagnoses platform, terminal, backend, metadata, and live PCM readiness
- distinguishes bass, voice, detail, cadence, and transients
- recomposes the same body identities into micro, chimney, basin, and current habitats
- offers Text and foreground-only Fluid output materials without changing organism physics
- carries weight, agitation, tension, intimacy, and release as an embodied acoustic posture
- adapts its 2-14 FPS cadence to acoustic activity and redraws only occupied contour changes
- displays optional local MPRIS media metadata
- offers four listening contexts: Podcast, Radio, Music, and Microphone
- supports keyboard and mouse controls through Python `curses`
- includes a synthetic demo that needs no audio device
- performs no network access, telemetry, recording, or plugin loading

## Requirements

- Linux
- Python 3.11 or newer
- a terminal with color and `curses` support
- one audio capture program: `pw-cat`, `parec`, or `ffmpeg`
- optionally, `playerctl` for media titles

Common package names include `pipewire-bin` and `pulseaudio-utils` on Debian/Ubuntu, `pipewire-utils` on Fedora, and `pipewire` on Arch Linux. Package names vary by distribution.

## Install

From a source checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

For development, install `-e '.[dev]'` instead.

## Run

```bash
lavatune
```

Run without live audio:

```bash
lavatune --demo
```

Check the machine and live audio path without entering the TUI:

```bash
lavatune --doctor
```

Use `--no-audio-probe` when only the installed programs and terminal capabilities should be checked. The doctor exits nonzero for a missing required backend or failed live PCM path, while optional media support and limited terminal color are warnings.

Select an explicit backend or monitor source:

```bash
lavatune --backend pipewire --source @DEFAULT_AUDIO_SINK@.monitor
```

Useful discovery commands:

```bash
lavatune --list-backends
lavatune --list-profiles
lavatune --list-themes
```

## Controls

The organism starts without configuration on screen. Press `Tab` to bring the control dock in or send it backstage again, and `q` to quit. Mouse clicks, the mouse wheel, and arrow keys adjust the selected control while the dock is open.

The dock has one daily choice: `Listening`. Choose `Podcast`, `Radio`, `Music`, or `Microphone`; it selects how the same acoustic facts become physical behavior. Podcast, Radio, and Music use system output. Microphone uses the local default input, shows an active capture state, and does not poll media metadata. Backend, source override, FPS, and diagnostic options remain available through configuration and the doctor command.

`Text` uses a validated one-column glyph ramp. `Fluid` draws analytic body contours directly from the organism, using quarter cells for curved boundaries and solid blocks for connected cores. Its short audio attacks enter a bounded, decaying perimeter wave and terminal-edge memory, so the surface ripples through cells rather than popping between them. The default remains CPU-bounded Fluid. The experimental `volume` material projects asymmetric rotating volumes with depth-tested surfaces and palette-facing colors. Its thermal-wax mode compresses authored role lanes into one central vessel and uses only per-body heat, buoyancy, viscosity, low-pass shape memory, and fixed pairwise adhesion: sustained pressure warms and lifts bodies, while at most one nearby warm pair briefly lends its existing lobes toward one another as a soft bridge. Other cores keep their normal separation, so the cluster stays countable.

Experimental `wax` is the true lava-lamp route: a fixed 64×32 density, heat, and flow lattice can merge into one continuous mass and later pinch back into separate return lobes. It does not allocate at terminal resolution; it projects only its occupied simulation bounds through the same solid quadrant glyphs. Wax is opt-in because its fixed simulation costs more than Fluid. Text, Fluid, Volume, and Wax preserve the terminal's real background and fall back to Text when UTF-8 output is unavailable.

## Audio behavior

Lavatune analyzes a monitor stream from the Linux audio stack. It does not save audio. The default monitor aliases are:

- PipeWire: `@DEFAULT_AUDIO_SINK@.monitor`
- PulseAudio and FFmpeg: `@DEFAULT_MONITOR@`

The first four bodies have stable roles: a large bass-sensitive ballast, a voice-oriented listener, a small detail-sensitive glint, and a neutral drifter. Lows move mass and create wall pressure, midrange circulates bodies, and highs texture their edges. Tempo changes the whole vessel while each body breathes, stretches, and turns on its own phase. Rapid repeated attacks add bounded flutter and circulation pressure without being mistaken for the main beat. Restrained passages establish a saturating readiness, so a confirmed snap can break the group open without growing larger simply because the calm lasted longer. Predictable motion builds expectation, giving interruption and resolution more physical consequence when context supports them. A transient can create physical impact and decaying afterglow, but a body forms a directional spike only when its listening band rises meaningfully above a recent rolling average. These relationships are intentionally elastic rather than frame-perfect synchronization, and Lavatune never assigns a named emotion to what it hears.

In `Radio`, one stable body becomes the voice carrier. Existing voice/mid energy drives its breath-like expansion and forward posture; fast detail creates only a small local consonant flick; a pause becomes a visible release. The other active bodies orient and drift toward it as listeners. A timbral handoff must remain credible for several seconds before the speaker changes, so the cast never swaps roles every syllable. This uses bounded acoustic envelopes only—no transcription or speaker identification.

The subjective behavior and review criteria are recorded in [`docs/DESIGN.md`](docs/DESIGN.md). Experimental Volume also uses local phrase memory: repeated cadence and sustained low-tone pressure can accumulate a held posture; an unexpected break can fracture it; sparse quiet after that break becomes an aftermath rather than an immediate reset. A credible break can leave different bounded residue in each organism; it only softens after a new, audible stable pattern—not merely because the song goes quiet. This is an audible-structure response, not a claim to know a song's meaning or the listener's feelings.

For a one-time calibration pass, `--trace-once SECONDS` captures the existing feature values from live system audio and then exits; it neither records PCM nor alters normal startup. It writes a temporary JSON trace to `/tmp/lavatune-trace.json` by default, which can be removed after review.

For motion tuning, `--motion-analysis SECONDS` runs the production mapper and organism physics against live system audio without entering the TUI. It writes only derived motion telemetry—speed, acceleration, travel, float/chop/stab cues, deformation, spikes, and afterglow—to `/tmp/lavatune-motion.json` by default, and prints a compact summary. Music uses the stab cue for short local impacts; radio keeps the shared drift envelope without that extra impulse. It never stores PCM:

```bash
lavatune --motion-analysis 30 --motion-output /tmp/lavatune-motion.json
```

The terminal-native TUI is the default presentation renderer. For an opt-in pixel companion view, add `--renderer canvas` (the older `--canvas` alias still works). It needs the local GTK 3/PyGObject runtime and reuses the exact same audio analysis, phrase state, and organism physics through one renderer-neutral presentation frame. It draws at native window resolution with four organisms and two fixed local surfaces each; it does not use GPU shaders or a full-screen scalar field. Canvas is experimental; terminal mode remains the portable product.

If automatic source selection fails, inspect sources with `wpctl status` or `pactl list short sources`, then pass the source with `--source`.

## Media metadata

When `playerctl` is available, Lavatune polls local MPRIS players and displays the playing title and artist. Metadata is sanitized and never sent over the network. Some browsers expose only the browser name rather than the website name.

Screenshots and terminal recordings can contain media titles. Redact them before posting publicly.

## Configuration

An example TOML override lives at [`configs/soft-afterglow.toml`](configs/soft-afterglow.toml):

```bash
lavatune --config configs/soft-afterglow.toml
```

For the experimental lava lamp, use [`configs/experimental-wax.toml`](configs/experimental-wax.toml):

```bash
lavatune --config configs/experimental-wax.toml
```


The compact tile integration accepts these environment variables:

- `LAVATUNE_COMPACT`
- `LAVATUNE_MAX_WIDTH`
- `LAVATUNE_MAX_HEIGHT`
- `LAVATUNE_TARGET_CELLS`

Older `CODEXDECK_LAVATUNE_*` names remain compatibility aliases during alpha.

Dock changes are saved atomically to `$XDG_CONFIG_HOME/lavatune/preferences.json`, or `~/.config/lavatune/preferences.json` when `XDG_CONFIG_HOME` is unset. An explicit `--config` launch ignores saved preferences and never writes them. Older theme, scene, palette, and glyph settings remain accepted even though the daily dock exposes only the smaller semantic control set.

Common backend and source failures are covered in [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md). The deterministic field benchmark and its measurement boundaries are documented in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

## Known limitations

- Linux is the only implemented platform.
- Audio capture depends on an installed `pw-cat`, `parec`, or PulseAudio-enabled `ffmpeg`.
- Monitor aliases vary across distributions and audio-server configurations.
- Browser MPRIS metadata may expose only the browser name.
- Alpha configuration and presentation details may change before `1.0`.

## Development

```bash
python -m unittest discover -s tests -v
ruff check .
python -m build
twine check dist/*
python scripts/verify_dist.py dist
python scripts/benchmark.py
python scripts/benchmark_render.py
```

The tests use synthetic signals and a pseudo-terminal; they do not need a live audio server or network access. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) follows one frame through the program, and [`CONTRIBUTING.md`](CONTRIBUTING.md) covers contribution boundaries.

## How this was made

Lavatune is a personal, human-led project built with substantial help from an AI coding agent. Tucker Vana (`@tuckeefro`) conceived the tool, directed its behavior and design, tested it in the Linux workspace it was made for, and maintains the accepted code. OpenAI Codex helped implement, test, document, and audit it.

That collaboration is described directly in [`AUTHORS.md`](AUTHORS.md). The project does not pretend every line was typed by hand, and it does not treat unreviewed model output as finished work.

## Security and privacy

Lavatune uses fixed subprocess argument lists without a shell, structured TOML parsing, bounded diagnostics, and sanitized media fields. Its local trust boundaries and vulnerability reporting process are documented in [`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE).
