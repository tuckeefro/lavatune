# Troubleshooting

Start with:

```bash
lavatune --doctor
```

The command checks Linux and Python compatibility, terminal color support, installed audio backends, optional media metadata support, and whether a short live PCM probe receives frames. It does not save audio.

## No capture backend

Install one of `pw-cat`, `parec`, or a build of `ffmpeg` with PulseAudio input support. Distribution package names differ; common packages are listed in the README.

Select a backend explicitly when more than one is installed:

```bash
lavatune --backend pipewire
lavatune --backend pulse
```

## Backend exists but no PCM arrives

Inspect the audio server outside Lavatune:

```bash
wpctl status
pactl list short sources
```

Then pass the monitor source as one argument:

```bash
lavatune --backend pipewire --source @DEFAULT_AUDIO_SINK@.monitor
```

A container, sandbox, remote shell, or service session may have the backend executable without permission to connect to the desktop audio server. The doctor reports that separately from a missing executable.

## Limited or incorrect colors

Run `lavatune --doctor --no-audio-probe` inside the target terminal. The intended palette needs 256-color support. Check that `TERM` describes the actual terminal or multiplexer instead of forcing a value globally.

## Missing media title

Media metadata is optional and requires `playerctl` plus an MPRIS-compatible local player. Some browsers publish only a browser-level identity or no page title. Audio response does not depend on metadata.

## Resizing or terminal corruption

Press `q` to exit cleanly. If a terminal was interrupted before cleanup, run `reset` to restore its display modes. Include terminal name, multiplexer, starting size, final size, and `lavatune --version` in a bug report, but redact media titles and device names.
