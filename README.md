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
- displays optional local MPRIS media metadata
- includes canonical listening, music, speech, and low-power operating modes
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

The three dock tabs are:

- `Modes`: operating mode, reactivity, and source type
- `Look`: palette, glyphs, density, detail, and diagnostics
- `System`: power profile, frame size, FPS, analysis, and backend

Reactivity personalities are `whisper`, `conversational`, and `electric`. The default uses buoyant motion, `soft-afterglow`, and conversational reactivity.

## Audio behavior

Lavatune analyzes a monitor stream from the Linux audio stack. It does not save audio. The default monitor aliases are:

- PipeWire: `@DEFAULT_AUDIO_SINK@.monitor`
- PulseAudio and FFmpeg: `@DEFAULT_MONITOR@`

The first four bodies have stable roles: a large bass-sensitive ballast, a voice-oriented listener, a small detail-sensitive glint, and a neutral drifter. Lows move mass and create wall pressure, midrange circulates bodies, highs texture their edges, cadence changes convection, and a transient selects one body for a localized impact and decaying afterglow. These relationships are intentionally elastic rather than frame-perfect synchronization.

The subjective behavior and review criteria are recorded in [`docs/DESIGN.md`](docs/DESIGN.md).

If automatic source selection fails, inspect sources with `wpctl status` or `pactl list short sources`, then pass the source with `--source`.

## Media metadata

When `playerctl` is available, Lavatune polls local MPRIS players and displays the playing title and artist. Metadata is sanitized and never sent over the network. Some browsers expose only the browser name rather than the website name.

Screenshots and terminal recordings can contain media titles. Redact them before posting publicly.

## Configuration

An example TOML override lives at [`configs/soft-afterglow.toml`](configs/soft-afterglow.toml):

```bash
lavatune --config configs/soft-afterglow.toml
```

The compact tile integration accepts these environment variables:

- `LAVATUNE_COMPACT`
- `LAVATUNE_MAX_WIDTH`
- `LAVATUNE_MAX_HEIGHT`
- `LAVATUNE_TARGET_CELLS`

Older `CODEXDECK_LAVATUNE_*` names remain compatibility aliases during alpha.

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
```

The tests use synthetic signals and a pseudo-terminal; they do not need a live audio server or network access. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) follows one frame through the program, and [`CONTRIBUTING.md`](CONTRIBUTING.md) covers contribution boundaries.

## How this was made

Lavatune is a personal, human-led project built with substantial help from an AI coding agent. Tucker Vana (`@tuckeefro`) conceived the tool, directed its behavior and design, tested it in the Linux workspace it was made for, and maintains the accepted code. OpenAI Codex helped implement, test, document, and audit it.

That collaboration is described directly in [`AUTHORS.md`](AUTHORS.md). The project does not pretend every line was typed by hand, and it does not treat unreviewed model output as finished work.

## Security and privacy

Lavatune uses fixed subprocess argument lists without a shell, structured TOML parsing, bounded diagnostics, and sanitized media fields. Its local trust boundaries and vulnerability reporting process are documented in [`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE).
